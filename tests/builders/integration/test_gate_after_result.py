from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, RunResult, RunStatus, WorkerName


def test_core_evaluates_gates_after_runtime_result_returns() -> None:
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
        summary="candidate result",
    )

    run_after_result = orchestrator.apply_result(result)
    assert run_after_result.current_stage == "acceptance_defined"
    assert run_after_result.status is RunStatus.RUNNING

    run_after_gate = orchestrator.advance_stage("run-1", "tests_written")
    assert run_after_gate.current_stage == "tests_written"
    assert run_after_gate.events[-1].event == "stage_advanced"
