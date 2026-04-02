from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, RunResult, RunStatus, WorkerName


def test_core_not_runtime_owns_advancement_truth() -> None:
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

    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="acceptance_defined",
        status=RunStatus.PASSED,
        summary="runtime thinks stage passed",
    )

    run = orchestrator.apply_result(result)

    assert run.current_stage == "acceptance_defined"
    assert run.status is RunStatus.RUNNING

    advanced = orchestrator.advance_stage("run-1", "tests_written", next_worker=WorkerName.MASON)
    assert advanced.current_stage == "tests_written"
