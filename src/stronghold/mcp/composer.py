"""Composer: composite tool orchestrator.

Composites are deterministic step graphs over atomic tools. The composer
itself is plain Python — no LLM is involved in orchestration. Each atomic
step is invoked through the injected ``CompositeRuntime``, which in
production is the Emissary's ``call_tool`` so every step gets the full
Sentinel/Keyward/Warden treatment.

Argument templating:
- ``$args.X``       resolves to the composite caller's ``args["X"]``
- ``$steps.Y.field`` resolves to ``prior_outputs["Y"]["field"]``
- ``$steps.Y``      resolves to the entire output of step ``Y``
- any other value passes through verbatim

``on_error`` policy per step:
- ``abort``  stop execution; emit partial=True with current outputs (default)
- ``skip``   move to the next step; emit partial=True
- ``retry``  retry the step once with the same args (v1: single retry)
- ``rollback``  not implemented in v1 (caller may treat as abort)

Sequential execution only in v1. ``parallel_group`` on a step is recorded
but not yet honoured — a v2 follow-up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.types.security import (
    CompositeResult,
    StepResult,
    ToolCallRequest,
    ToolCallResult,
    WardenVerdict,
)

if TYPE_CHECKING:
    from stronghold.protocols.security import CompositeRuntime
    from stronghold.types.security import (
        CompositeDefinition,
        CompositeStep,
        ToolFingerprint,
    )


class CompositeUnregisteredError(KeyError):
    """Raised when ``execute`` is called for an unregistered fingerprint."""


def _resolve_template(
    template: dict[str, Any],
    args: dict[str, Any],
    prior: dict[str, Any],
) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    for key, value in template.items():
        if isinstance(value, str) and value.startswith("$args."):
            resolved[key] = args.get(value[len("$args.") :])
        elif isinstance(value, str) and value.startswith("$steps."):
            tail = value[len("$steps.") :]
            if "." in tail:
                step_id, field = tail.split(".", 1)
                step_output = prior.get(step_id)
                if isinstance(step_output, dict):
                    resolved[key] = step_output.get(field)
                else:
                    resolved[key] = None
            else:
                resolved[key] = prior.get(tail)
        else:
            resolved[key] = value
    return resolved


class Composer:
    """In-memory composite tool orchestrator."""

    def __init__(self) -> None:
        self._registry: dict[str, CompositeDefinition] = {}

    def register(self, definition: CompositeDefinition) -> None:
        self._registry[definition.fingerprint.value] = definition

    def is_registered(self, fingerprint: ToolFingerprint) -> bool:
        return fingerprint.value in self._registry

    async def execute(
        self,
        request: ToolCallRequest,
        runtime: CompositeRuntime,
    ) -> ToolCallResult:
        definition = self._registry.get(request.fingerprint.value)
        if definition is None:
            raise CompositeUnregisteredError(request.fingerprint.name)

        outputs: dict[str, Any] = {}
        step_results: list[StepResult] = []
        partial = False

        for step in definition.steps:
            step_result, step_outcome_partial = await self._run_step(
                step=step,
                request=request,
                outputs=outputs,
                runtime=runtime,
            )
            step_results.append(step_result)

            if step_result.error is None:
                outputs[step.id] = step_result.output
            else:
                partial = True
                if step.on_error == "abort":
                    break
                # "skip" continues; other policies fall through as abort for v1.
                if step.on_error not in ("skip", "retry"):
                    break

            if step_outcome_partial:
                partial = True

        composite_result = CompositeResult(
            outputs=outputs,
            step_results=tuple(step_results),
            partial=partial,
        )
        return _wrap(composite_result)

    async def _run_step(
        self,
        *,
        step: CompositeStep,
        request: ToolCallRequest,
        outputs: dict[str, Any],
        runtime: CompositeRuntime,
    ) -> tuple[StepResult, bool]:
        resolved_args = _resolve_template(step.args_template, request.args, outputs)
        step_call_id = f"{request.call_id}::{step.id}" if request.call_id else step.id
        step_request = ToolCallRequest(
            fingerprint=step.tool,
            args=resolved_args,
            auth=request.auth,
            session=request.session,
            call_id=step_call_id,
        )

        attempts = 2 if step.on_error == "retry" else 1
        last_exception: Exception | None = None
        last_result: ToolCallResult | None = None

        for _ in range(attempts):
            try:
                result = await runtime.call(step_request)
            except Exception as exc:  # noqa: BLE001 — orchestrator must catch all
                last_exception = exc
                continue
            last_result = result
            last_exception = None
            if not result.is_error:
                return StepResult(step_id=step.id, output=result.content), False

        if last_exception is not None:
            return (
                StepResult(step_id=step.id, output=None, error=str(last_exception)),
                True,
            )
        if last_result is None:
            return (
                StepResult(step_id=step.id, output=None, error="no result produced"),
                True,
            )
        return (
            StepResult(
                step_id=step.id,
                output=last_result.content,
                error="step_returned_error",
            ),
            True,
        )


def _wrap(result: CompositeResult) -> ToolCallResult:
    """Wrap a CompositeResult as a ToolCallResult for Emissary's caller."""
    return ToolCallResult(
        content={
            "outputs": result.outputs,
            "steps": [
                {"id": s.step_id, "error": s.error, "output": s.output} for s in result.step_results
            ],
        },
        is_error=False,
        warden_verdict=WardenVerdict(clean=True),
        partial=result.partial,
    )
