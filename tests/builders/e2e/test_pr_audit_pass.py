from __future__ import annotations

import pytest

from stronghold.builders import (
    ArtifactRef,
    BuildersOrchestrator,
    BuildersRuntime,
    InMemoryArtifactStore,
    InMemoryGitHubService,
    RunResult,
    RunStatus,
    WorkerName,
)


@pytest.mark.asyncio
async def test_pr_audit_workflow_can_pass_without_rework() -> None:
    orchestrator = BuildersOrchestrator()
    runtime = BuildersRuntime()
    artifacts = InMemoryArtifactStore()
    github = InMemoryGitHubService()

    pr = github.open_pr(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
        title="feat: resolve #42",
        body="Automated Builders PR",
    )
    orchestrator.create_run(
        run_id="run-1-audit",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-audit",
        initial_stage="implementation_started",
        initial_worker=WorkerName.AUDITOR,
    )

    async def auditor_handler(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="Audit passed",
            artifacts=[
                ArtifactRef(
                    type="audit_report",
                    path="runs/run-1-audit/audit.json",
                    producer="auditor",
                    metadata={"pr_number": pr.pr_number, "verdict": "pass"},
                )
            ],
        )

    runtime.register(WorkerName.AUDITOR, "implementation_started", auditor_handler)

    result = await runtime.execute(orchestrator.build_request("run-1-audit"))
    for artifact in result.artifacts:
        artifacts.store(artifact)
    run = orchestrator.apply_result(result, next_stage="implementation_ready")

    assert run.current_stage == "implementation_ready"
    assert artifacts.list_for_run("run-1-audit")[0].metadata["verdict"] == "pass"
