from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, InMemoryGitHubService, RunResult, RunStatus, WorkerName


def test_blocked_run_is_surfaced_end_to_end() -> None:
    orchestrator = BuildersOrchestrator()
    github = InMemoryGitHubService()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="acceptance_defined",
        initial_worker=WorkerName.FRANK,
    )
    run = orchestrator.apply_result(
        RunResult(
            run_id="run-1",
            worker=WorkerName.FRANK,
            stage="acceptance_defined",
            status=RunStatus.BLOCKED,
            summary="Need user clarification",
        )
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="blocked",
        body="Blocked: Need user clarification",
    )

    assert run.status is RunStatus.BLOCKED
    assert github.list_issue_updates(run_id="run-1")[0].stage == "blocked"
