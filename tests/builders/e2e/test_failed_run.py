from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, InMemoryGitHubService, RunResult, RunStatus, WorkerName


def test_failed_run_is_surfaced_end_to_end() -> None:
    orchestrator = BuildersOrchestrator()
    github = InMemoryGitHubService()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="implementation_started",
        initial_worker=WorkerName.MASON,
    )
    run = orchestrator.apply_result(
        RunResult(
            run_id="run-1",
            worker=WorkerName.MASON,
            stage="implementation_started",
            status=RunStatus.FAILED,
            summary="CI irrecoverably failed",
        )
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="failed",
        body="Failed: CI irrecoverably failed",
    )

    assert run.status is RunStatus.FAILED
    assert github.list_issue_updates(run_id="run-1")[0].stage == "failed"
