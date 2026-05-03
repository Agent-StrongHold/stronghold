"""Composer contract tests."""

from __future__ import annotations

import pytest

from stronghold.mcp.composer import Composer, CompositeUnregisteredError
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.security import (
    CompositeDefinition,
    CompositeStep,
    ToolCallRequest,
    ToolCallResult,
    ToolFingerprint,
    TrustTier,
    WardenVerdict,
)


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _fp(name: str) -> ToolFingerprint:
    return ToolFingerprint(value=f"fp-{name}", name=name, schema_hash=f"sh-{name}")


class _Runtime:
    """Minimal CompositeRuntime fake. Records every call and returns canned
    responses keyed on tool name, or raises on a configured tool name."""

    def __init__(self) -> None:
        self.responses: dict[str, ToolCallResult] = {}
        self.exceptions: dict[str, Exception] = {}
        self.calls: list[ToolCallRequest] = []

    def set_response(self, tool_name: str, content: object, is_error: bool = False) -> None:
        self.responses[tool_name] = ToolCallResult(
            content=content,
            is_error=is_error,
            warden_verdict=WardenVerdict(clean=True),
        )

    def set_exception(self, tool_name: str, exc: Exception) -> None:
        self.exceptions[tool_name] = exc

    async def call(self, request: ToolCallRequest) -> ToolCallResult:
        self.calls.append(request)
        if request.fingerprint.name in self.exceptions:
            raise self.exceptions[request.fingerprint.name]
        return self.responses.get(
            request.fingerprint.name,
            ToolCallResult(
                content={"ok": True, "tool": request.fingerprint.name},
                is_error=False,
                warden_verdict=WardenVerdict(clean=True),
            ),
        )


def _composite(
    steps: list[CompositeStep],
    *,
    name: str = "triage",
    tier: TrustTier = TrustTier.T1,
) -> CompositeDefinition:
    return CompositeDefinition(
        fingerprint=_fp(name),
        name=name,
        description="",
        input_schema={},
        output_schema={},
        steps=tuple(steps),
        trust_tier=tier,
    )


# --- happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_step_executes_and_returns_outputs() -> None:
    composer = Composer()
    composer.register(
        _composite([CompositeStep(id="s1", tool=_fp("github_search"), args_template={})])
    )
    runtime = _Runtime()

    result = await composer.execute(
        ToolCallRequest(
            fingerprint=_fp("triage"),
            args={"q": "bug"},
            auth=_alice(),
            call_id="c1",
        ),
        runtime,
    )
    assert result.is_error is False
    assert result.partial is False
    assert isinstance(result.content, dict)
    assert "outputs" in result.content
    assert "s1" in result.content["outputs"]


@pytest.mark.asyncio
async def test_args_template_resolves_caller_args_and_step_outputs() -> None:
    composer = Composer()
    composer.register(
        _composite(
            [
                CompositeStep(
                    id="s1",
                    tool=_fp("search"),
                    args_template={"q": "$args.q"},
                ),
                CompositeStep(
                    id="s2",
                    tool=_fp("summarise"),
                    args_template={"text": "$steps.s1.summary"},
                ),
            ]
        )
    )
    runtime = _Runtime()
    runtime.set_response("search", {"summary": "found 5", "raw": ["a", "b"]})

    await composer.execute(
        ToolCallRequest(
            fingerprint=_fp("triage"),
            args={"q": "bug"},
            auth=_alice(),
            call_id="c1",
        ),
        runtime,
    )

    assert len(runtime.calls) == 2
    assert runtime.calls[0].args == {"q": "bug"}
    assert runtime.calls[1].args == {"text": "found 5"}


@pytest.mark.asyncio
async def test_step_call_id_is_namespaced_under_composite() -> None:
    composer = Composer()
    composer.register(_composite([CompositeStep(id="s1", tool=_fp("search"), args_template={})]))
    runtime = _Runtime()
    await composer.execute(
        ToolCallRequest(
            fingerprint=_fp("triage"),
            args={},
            auth=_alice(),
            call_id="parent",
        ),
        runtime,
    )
    assert runtime.calls[0].call_id == "parent::s1"


# --- error policies ---------------------------------------------------------


@pytest.mark.asyncio
async def test_abort_on_error_stops_execution_and_marks_partial() -> None:
    composer = Composer()
    composer.register(
        _composite(
            [
                CompositeStep(id="s1", tool=_fp("search"), args_template={}, on_error="abort"),
                CompositeStep(id="s2", tool=_fp("summarise"), args_template={}, on_error="abort"),
            ]
        )
    )
    runtime = _Runtime()
    runtime.set_exception("search", RuntimeError("backend down"))

    result = await composer.execute(
        ToolCallRequest(fingerprint=_fp("triage"), args={}, auth=_alice(), call_id="c1"),
        runtime,
    )
    assert result.partial is True
    assert len(runtime.calls) == 1
    assert runtime.calls[0].fingerprint.name == "search"
    assert "s1" in {step["id"] for step in result.content["steps"]}
    assert "s2" not in {step["id"] for step in result.content["steps"]}


@pytest.mark.asyncio
async def test_skip_on_error_continues_to_next_step() -> None:
    composer = Composer()
    composer.register(
        _composite(
            [
                CompositeStep(id="s1", tool=_fp("search"), args_template={}, on_error="skip"),
                CompositeStep(id="s2", tool=_fp("summarise"), args_template={}, on_error="abort"),
            ]
        )
    )
    runtime = _Runtime()
    runtime.set_exception("search", RuntimeError("intermittent"))

    result = await composer.execute(
        ToolCallRequest(fingerprint=_fp("triage"), args={}, auth=_alice(), call_id="c1"),
        runtime,
    )
    assert result.partial is True
    step_ids = {step["id"] for step in result.content["steps"]}
    assert "s1" in step_ids
    assert "s2" in step_ids


@pytest.mark.asyncio
async def test_retry_on_error_attempts_twice() -> None:
    composer = Composer()
    composer.register(
        _composite(
            [
                CompositeStep(id="s1", tool=_fp("flaky"), args_template={}, on_error="retry"),
            ]
        )
    )
    runtime = _Runtime()
    runtime.set_exception("flaky", RuntimeError("once"))

    result = await composer.execute(
        ToolCallRequest(fingerprint=_fp("triage"), args={}, auth=_alice(), call_id="c1"),
        runtime,
    )
    # Two attempts, both raised because the runtime always raises.
    assert len([c for c in runtime.calls if c.fingerprint.name == "flaky"]) == 2
    assert result.partial is True


@pytest.mark.asyncio
async def test_step_returning_is_error_marks_partial_and_aborts_by_default() -> None:
    composer = Composer()
    composer.register(
        _composite(
            [
                CompositeStep(id="s1", tool=_fp("search"), args_template={}, on_error="abort"),
                CompositeStep(id="s2", tool=_fp("summarise"), args_template={}, on_error="abort"),
            ]
        )
    )
    runtime = _Runtime()
    runtime.set_response("search", {"err": "boom"}, is_error=True)

    result = await composer.execute(
        ToolCallRequest(fingerprint=_fp("triage"), args={}, auth=_alice(), call_id="c1"),
        runtime,
    )
    assert result.partial is True
    assert len(runtime.calls) == 1


# --- registry --------------------------------------------------------------


@pytest.mark.asyncio
async def test_unregistered_composite_raises() -> None:
    composer = Composer()
    runtime = _Runtime()
    with pytest.raises(CompositeUnregisteredError):
        await composer.execute(
            ToolCallRequest(
                fingerprint=_fp("missing"),
                args={},
                auth=_alice(),
                call_id="c1",
            ),
            runtime,
        )


@pytest.mark.asyncio
async def test_is_registered_reflects_register() -> None:
    composer = Composer()
    fingerprint = _fp("triage")
    assert composer.is_registered(fingerprint) is False
    composer.register(_composite([], name="triage"))
    assert composer.is_registered(fingerprint) is True
