from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, RunResult, RunStatus, WorkerName


def test_blocked_runs_are_persisted_and_reported() -> None:
    orchestrator = BuildersOrchestrator()
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
            summary="Need clarification",
        )
    )

    assert run.status is RunStatus.BLOCKED
    assert run.current_stage == "blocked"
    assert run.events[-1].event == "runtime_blocked"
