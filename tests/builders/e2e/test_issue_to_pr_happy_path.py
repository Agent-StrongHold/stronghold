from __future__ import annotations

import pytest

from stronghold.builders import (
    ArtifactRef,
    BuildersOrchestrator,
    BuildersRuntime,
    InMemoryArtifactStore,
    InMemoryGitHubService,
    InMemoryWorkspaceService,
    RunResult,
    RunStatus,
    WorkerName,
)


@pytest.mark.asyncio
async def test_full_happy_path_issue_to_pr_flow() -> None:
    orchestrator = BuildersOrchestrator()
    runtime = BuildersRuntime()
    workspaces = InMemoryWorkspaceService()
    artifacts = InMemoryArtifactStore()
    github = InMemoryGitHubService()

    workspace = workspaces.create(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
    )
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref=workspace.workspace_id,
        initial_stage="acceptance_defined",
        initial_worker=WorkerName.FRANK,
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="acceptance_defined",
        body="Frank started",
    )

    async def frank_handler(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="Acceptance criteria and tests ready",
            artifacts=[
                ArtifactRef(
                    type="acceptance_criteria",
                    path="runs/run-1/criteria.json",
                    producer="frank",
                ),
                ArtifactRef(
                    type="test_plan",
                    path="runs/run-1/test-plan.json",
                    producer="frank",
                ),
            ],
        )

    async def mason_handler(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="Implementation ready for PR",
            artifacts=[
                ArtifactRef(
                    type="implementation_summary",
                    path="runs/run-1/implementation.json",
                    producer="mason",
                ),
                ArtifactRef(
                    type="validation_report",
                    path="runs/run-1/validation.json",
                    producer="mason",
                ),
            ],
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", frank_handler)
    runtime.register(WorkerName.MASON, "implementation_started", mason_handler)

    frank_result = await runtime.execute(orchestrator.build_request("run-1"))
    for artifact in frank_result.artifacts:
        artifacts.store(artifact)
    orchestrator.apply_result(frank_result, next_stage="tests_written")
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="tests_written",
        body="Frank delivered criteria and tests",
    )

    orchestrator.advance_stage("run-1", "implementation_started", next_worker=WorkerName.MASON)
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="implementation_started",
        body="Mason started",
    )
    mason_result = await runtime.execute(orchestrator.build_request("run-1"))
    for artifact in mason_result.artifacts:
        artifacts.store(artifact)
    orchestrator.apply_result(mason_result, next_stage="implementation_ready")
    orchestrator.advance_stage("run-1", "quality_checks_passed")
    completed = orchestrator.advance_stage("run-1", "completed")

    pr = github.open_pr(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
        title="feat: resolve #42",
        body="Automated Builders PR",
    )

    assert completed.status is RunStatus.PASSED
    assert pr.pr_number == 1
    assert len(artifacts.list_for_run("run-1")) == 4
    assert [update.stage for update in github.list_issue_updates(run_id="run-1")] == [
        "acceptance_defined",
        "implementation_started",
        "tests_written",
    ]
