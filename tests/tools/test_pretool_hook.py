"""Tests for PreToolCall hook chain in ToolDispatcher (S1.2)."""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.protocols.tool_hooks import (
    AllowVerdict,
    DenyVerdict,
    PreToolCallVerdict,
    RepairVerdict,
)
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.errors import ConfigError
from stronghold.types.tool import ToolDefinition, ToolResult


def _make_auth(user_id: str = "u1", org_id: str = "org-1") -> AuthContext:
    return AuthContext(
        user_id=user_id,
        org_id=org_id,
        team_id="team-1",
        kind=IdentityKind.USER,
    )


class _StaticHook:
    """Hook that returns a preset verdict and records every call."""

    def __init__(self, name: str, verdict: PreToolCallVerdict) -> None:
        self.name = name
        self._verdict = verdict
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth: AuthContext,
    ) -> PreToolCallVerdict:
        self.calls.append((tool_name, dict(arguments)))
        return self._verdict


def _register_echo_tool(registry: InMemoryToolRegistry) -> list[dict[str, Any]]:
    """Register a tool that echoes the arguments it received. Returns a mutable list of calls."""
    calls: list[dict[str, Any]] = []

    async def echo(args: dict[str, Any]) -> ToolResult:
        calls.append(args)
        return ToolResult(success=True, content=f"echo:{args!r}")

    registry.register(ToolDefinition(name="echo"), executor=echo)
    return calls


async def test_empty_chain_is_passthrough() -> None:
    """AC 1: empty hook chain → zero behavior change (no auth required)."""
    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)
    dispatcher = ToolDispatcher(registry, hooks=())
    result = await dispatcher.execute("echo", {"x": 1})
    assert "echo:" in result
    assert calls == [{"x": 1}]


async def test_allow_chain_runs_executor() -> None:
    """AC 2: all-Allow chain → executor runs with original args."""
    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)
    hook_a = _StaticHook("a", AllowVerdict())
    hook_b = _StaticHook("b", AllowVerdict())
    audit = InMemoryAuditLog()
    dispatcher = ToolDispatcher(registry, hooks=(hook_a, hook_b), audit_log=audit)
    await dispatcher.execute("echo", {"x": 1}, auth=_make_auth())
    assert calls == [{"x": 1}]
    assert hook_a.calls == [("echo", {"x": 1})]
    assert hook_b.calls == [("echo", {"x": 1})]


async def test_single_deny_short_circuits() -> None:
    """AC 3: one DenyVerdict aborts the chain; executor is not called."""
    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)
    hook_a = _StaticHook("a", AllowVerdict())
    hook_b = _StaticHook("b", DenyVerdict(reason="no", hook_name="b"))
    hook_c = _StaticHook("c", AllowVerdict())
    dispatcher = ToolDispatcher(registry, hooks=(hook_a, hook_b, hook_c))
    result = await dispatcher.execute("echo", {"x": 1}, auth=_make_auth())
    assert "denied by b" in result
    assert "no" in result
    assert calls == []  # executor never ran
    assert hook_c.calls == []  # downstream hook did not run


async def test_repair_mutates_args_for_next_hook() -> None:
    """AC 4: RepairVerdict propagates new args to subsequent hooks."""
    registry = InMemoryToolRegistry()
    _register_echo_tool(registry)
    hook_a = _StaticHook(
        "a",
        RepairVerdict(new_arguments={"x": 99, "fixed": True}, reason="normalize", hook_name="a"),
    )
    hook_b = _StaticHook("b", AllowVerdict())
    dispatcher = ToolDispatcher(registry, hooks=(hook_a, hook_b))
    await dispatcher.execute("echo", {"x": 1}, auth=_make_auth())
    # Hook b sees repaired args, not the original
    assert hook_b.calls == [("echo", {"x": 99, "fixed": True})]


async def test_repair_chain_final_args_reach_executor() -> None:
    """AC 4: final repaired args are what the executor gets."""
    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)
    hook_a = _StaticHook(
        "a",
        RepairVerdict(new_arguments={"x": 2}, reason="+1", hook_name="a"),
    )
    hook_b = _StaticHook(
        "b",
        RepairVerdict(new_arguments={"x": 3}, reason="+1", hook_name="b"),
    )
    dispatcher = ToolDispatcher(registry, hooks=(hook_a, hook_b))
    await dispatcher.execute("echo", {"x": 1}, auth=_make_auth())
    assert calls == [{"x": 3}]


async def test_hook_order_is_preserved() -> None:
    """AC 5: hooks run in the order they were registered."""
    registry = InMemoryToolRegistry()
    _register_echo_tool(registry)

    order: list[str] = []

    class _OrderHook:
        def __init__(self, n: str) -> None:
            self.name = n

        async def check(
            self,
            tool_name: str,
            arguments: dict[str, Any],
            auth: AuthContext,
        ) -> PreToolCallVerdict:
            order.append(self.name)
            return AllowVerdict()

    dispatcher = ToolDispatcher(
        registry,
        hooks=(_OrderHook("1"), _OrderHook("2"), _OrderHook("3")),
    )
    await dispatcher.execute("echo", {}, auth=_make_auth())
    assert order == ["1", "2", "3"]


async def test_deny_without_auth_raises_config_error() -> None:
    """AC 7: non-empty hook chain + auth=None → ConfigError (fail-closed)."""
    registry = InMemoryToolRegistry()
    _register_echo_tool(registry)
    hook = _StaticHook("a", AllowVerdict())
    dispatcher = ToolDispatcher(registry, hooks=(hook,))
    with pytest.raises(ConfigError):
        await dispatcher.execute("echo", {}, auth=None)


async def test_slow_hook_times_out_and_allows() -> None:
    """AC 8: slow hook → timeout treated as Allow (fail-open on hook failure only)."""
    import asyncio

    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)

    class _SlowHook:
        name = "slow"

        async def check(
            self,
            tool_name: str,
            arguments: dict[str, Any],
            auth: AuthContext,
        ) -> PreToolCallVerdict:
            await asyncio.sleep(5)
            return DenyVerdict(reason="too late", hook_name="slow")

    dispatcher = ToolDispatcher(registry, hooks=(_SlowHook(),), hook_timeout=0.05)
    result = await dispatcher.execute("echo", {"x": 1}, auth=_make_auth())
    assert "echo:" in result
    assert calls == [{"x": 1}]


async def test_explicit_fail_closed_deny_at_chain_end() -> None:
    """AC 8: a fail-closed operator can put a trailing deny-by-default hook to override."""
    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)
    always_deny = _StaticHook(
        "trailing_deny",
        DenyVerdict(reason="default deny", hook_name="trailing_deny"),
    )
    dispatcher = ToolDispatcher(registry, hooks=(always_deny,))
    result = await dispatcher.execute("echo", {}, auth=_make_auth())
    assert "denied by trailing_deny" in result
    assert calls == []


async def test_audit_entry_written_for_each_verdict() -> None:
    """AC 6: every hook verdict (allow/deny/repair) produces an audit entry."""
    registry = InMemoryToolRegistry()
    _register_echo_tool(registry)
    hook_a = _StaticHook("a", AllowVerdict())
    hook_b = _StaticHook("b", RepairVerdict(new_arguments={}, reason="r", hook_name="b"))
    hook_c = _StaticHook("c", DenyVerdict(reason="nope", hook_name="c"))
    audit = InMemoryAuditLog()
    dispatcher = ToolDispatcher(
        registry,
        hooks=(hook_a, hook_b, hook_c),
        audit_log=audit,
    )
    await dispatcher.execute("echo", {"x": 1}, auth=_make_auth())
    entries = await audit.get_entries(org_id="org-1")
    hook_entries = [e for e in entries if e.tool_name == "echo" and e.boundary == "pretool_hook"]
    assert len(hook_entries) == 3
    verdicts = {e.verdict for e in hook_entries}
    assert verdicts == {"allow", "repair", "deny"}


async def test_existing_call_sites_without_auth_still_work() -> None:
    """AC 1 safety net: dispatcher with no hooks still accepts old-style call (tool_name, args)."""
    registry = InMemoryToolRegistry()
    calls = _register_echo_tool(registry)
    dispatcher = ToolDispatcher(registry)
    # Old-style call — no auth, no hooks configured
    result = await dispatcher.execute("echo", {"x": 1})
    assert "echo:" in result
    assert calls == [{"x": 1}]
