"""Tests for BuildersWorkflow — verifies the workflow class works without FastAPI."""

from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName
from stronghold.builders.workflow import BuildersWorkflow, STAGE_SEQUENCE, STAGE_HANDLERS
from tests.builders.test_workflow_smoke import SmartFakeLLM, WorkflowToolDispatcher
from tests.fakes import make_test_container


class TestBuildersWorkflowClass:
    def test_constants_exported(self) -> None:
        assert len(STAGE_SEQUENCE) >= 5
        assert "issue_analyzed" in STAGE_HANDLERS

    def test_build_pipeline_returns_runtime_pipeline(self) -> None:
        container = make_test_container()
        wf = BuildersWorkflow(BuildersOrchestrator(), container)
        pipeline = wf.build_pipeline()
        assert hasattr(pipeline, "analyze_issue")
        assert hasattr(pipeline, "auditor_review")

    def test_serialize_run(self) -> None:
        orch = BuildersOrchestrator()
        orch.create_run(
            run_id="run-ser", repo="o/r", issue_number=1,
            branch="b", workspace_ref="ws",
            initial_stage="issue_analyzed", initial_worker=WorkerName.FRANK,
        )
        run = orch._runs["run-ser"]
        data = BuildersWorkflow.serialize_run(run)
        assert data["run_id"] == "run-ser"
        assert "status" in data

    async def test_execute_full_workflow_without_fastapi(self) -> None:
        """BuildersWorkflow can run the full workflow without a TestClient."""
        import asyncio as _asyncio

        llm = SmartFakeLLM()
        container = make_test_container(fake_llm=llm)
        td = WorkflowToolDispatcher()
        container.tool_dispatcher = td

        orch = BuildersOrchestrator()
        orch.create_run(
            run_id="run-wf", repo="owner/repo", issue_number=42,
            branch="mason/42", workspace_ref="ws-wf",
            initial_stage="issue_analyzed", initial_worker=WorkerName.FRANK,
        )

        from stronghold.api.routes.builders import _build_service_auth

        service_auth = _build_service_auth(container)
        wf = BuildersWorkflow(orch, container)
        await wf.execute_full_workflow("run-wf", service_auth=service_auth)
        await _asyncio.sleep(0)

        run = orch._runs["run-wf"]
        # Should complete or at least progress through stages
        assert len(run.events) >= 3
