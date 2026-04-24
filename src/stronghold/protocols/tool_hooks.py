"""PreToolCall hook protocol: single insertion point for per-call policy.

A hook inspects (tool_name, arguments, auth) before ToolDispatcher runs the
executor. Verdicts:

- AllowVerdict:  let the call proceed unchanged (or with prior repairs).
- DenyVerdict:   abort the chain; the dispatcher returns an error string,
                 the executor never runs. First deny short-circuits.
- RepairVerdict: mutate the arguments for subsequent hooks and the executor.
                 Order matters — each hook sees the repaired args from
                 upstream hooks, not the caller-provided args.

Composition rules:
- Hooks run in the order configured on ToolDispatcher.
- Timeout per hook is bounded (default 1s); a timeout is treated as Allow.
  This is fail-open on *hook failure*. Operators who need fail-closed semantics
  append a deny-by-default hook at the chain end.
- auth=None with a non-empty hook chain raises ConfigError (fail-closed on
  the wiring mistake, since every hook expects an AuthContext).

Consumed by: ToolDispatcher.execute(). Implemented by: ToolScopeHook (S2.1),
Sentinel profiles (S2.2), CasbinToolPolicy (existing RBAC), scope_widen_tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext


@dataclass(frozen=True)
class AllowVerdict:
    """Hook had no objection; call proceeds."""


@dataclass(frozen=True)
class DenyVerdict:
    """Hook blocks the call; dispatcher aborts with an error string."""

    reason: str
    hook_name: str


@dataclass(frozen=True)
class RepairVerdict:
    """Hook rewrites the arguments; subsequent hooks and the executor see new_arguments."""

    new_arguments: dict[str, Any]
    reason: str
    hook_name: str


PreToolCallVerdict = AllowVerdict | DenyVerdict | RepairVerdict


@runtime_checkable
class PreToolCallHook(Protocol):
    """Pre-dispatch tool-call interceptor.

    Implementations must set a `name` class-level attribute so audit entries
    can attribute verdicts to a specific hook.
    """

    name: str

    async def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        auth: AuthContext,
    ) -> PreToolCallVerdict:
        """Return Allow, Deny, or Repair for this tool call."""
        ...
