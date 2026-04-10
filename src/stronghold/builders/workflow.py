"""Builders workflow orchestration.

Extracted from api/routes/builders.py (Phase 4) to keep the route layer thin
and the workflow testable without FastAPI. The route handlers delegate to
BuildersWorkflow for all non-HTTP concerns.

The execute methods are thin wrappers around the module-level functions in
routes/builders.py. Future PRs will move those functions here entirely.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.builders.orchestrator import BuildersOrchestrator

logger = logging.getLogger("stronghold.builders.workflow")

# ── Constants (authoritative source) ─────────────────────────────────

MAX_STAGE_RETRIES = 3
MAX_OUTER_LOOPS = 3

STAGE_SEQUENCE = [
    "issue_analyzed",
    "acceptance_defined",
    "tests_written",
    "implementation_started",
    "implementation_ready",
    "quality_checks_passed",
]

UI_STAGE_SEQUENCE = [
    "ui_analyzed",
    "ui_criteria_defined",
    "ui_tests_written",
    "ui_implemented",
    "ui_verified",
]

STAGE_HANDLERS: dict[str, str] = {
    "issue_analyzed": "analyze_issue",
    "acceptance_defined": "define_acceptance_criteria",
    "tests_written": "write_tests",
    "implementation_started": "implement",
    "implementation_ready": "run_quality_gates",
    "quality_checks_passed": "final_verification",
}

STAGE_WORKER: dict[str, str] = {
    "issue_analyzed": "frank",
    "acceptance_defined": "frank",
    "tests_written": "mason",
    "implementation_started": "mason",
    "implementation_ready": "mason",
    "quality_checks_passed": "mason",
}

UI_STAGE_HANDLERS: dict[str, str] = {
    "ui_analyzed": "analyze_ui",
    "ui_criteria_defined": "define_ui_criteria",
    "ui_tests_written": "write_ui_tests",
    "ui_implemented": "implement_ui",
    "ui_verified": "verify_ui",
}

UI_STAGE_WORKER: dict[str, str] = {
    "ui_analyzed": "piper",
    "ui_criteria_defined": "piper",
    "ui_tests_written": "glazier",
    "ui_implemented": "glazier",
    "ui_verified": "glazier",
}


# ── Workflow class ───────────────────────────────────────────────────


class BuildersWorkflow:
    """Orchestrates a builders run from create_run through PR creation.

    Wraps the workflow execution functions. Route handlers delegate to
    this class for all non-HTTP concerns (stage execution, outer loop,
    PR creation, Warden scanning).
    """

    def __init__(self, orchestrator: BuildersOrchestrator, container: Any) -> None:
        self._orch = orchestrator
        self._container = container

    def build_pipeline(self) -> Any:
        """Build a RuntimePipeline from the container's dependencies."""
        from stronghold.builders.pipeline import RuntimePipeline

        return RuntimePipeline(
            llm=self._container.llm,
            tool_dispatcher=self._container.tool_dispatcher,
            prompt_manager=getattr(self._container, "prompt_manager", None),
        )

    @staticmethod
    def serialize_run(run: Any) -> dict[str, Any]:
        """Serialize a RunState for API responses."""
        # Delegate to the existing function in routes/builders.py
        from stronghold.api.routes.builders import _serialize_run

        return _serialize_run(run)

    async def execute_one_stage(
        self,
        run_id: str,
        *,
        service_auth: Any,
        ctx: Any | None = None,
        trace: Any | None = None,
    ) -> None:
        """Execute a single stage. Delegates to the existing function."""
        from stronghold.api.routes.builders import _execute_one_stage

        await _execute_one_stage(
            run_id, self._orch, self._container, service_auth,
            ctx=ctx, trace=trace,
        )

    async def execute_full_workflow(
        self,
        run_id: str,
        *,
        service_auth: Any,
    ) -> None:
        """Execute all stages in sequence. Delegates to the existing function."""
        from stronghold.api.routes.builders import _execute_full_workflow

        await _execute_full_workflow(
            run_id, self._orch, self._container, service_auth,
        )
