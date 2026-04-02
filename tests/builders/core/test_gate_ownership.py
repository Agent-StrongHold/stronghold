from __future__ import annotations

from stronghold.builders import ArtifactRef, BuildersOrchestrator, RunResult, RunStatus, WorkerName


def test_runtime_pass_result_does_not_self_complete_run() -> None:
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
        summary="Acceptance criteria created",
        artifacts=[
            ArtifactRef(
                type="acceptance_criteria",
                path="runs/run-1/criteria.json",
                producer="frank",
            )
        ],
    )

    run = orchestrator.apply_result(result)

    assert run.status is RunStatus.RUNNING
    assert run.current_stage == "acceptance_defined"
    assert len(run.artifacts) == 1
    assert run.events[-1].event == "runtime_passed"


def test_core_must_explicitly_advance_after_runtime_passes() -> None:
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
        summary="Acceptance criteria created",
    )

    run = orchestrator.apply_result(result, next_stage="tests_written")

    assert run.current_stage == "tests_written"
    assert run.status is RunStatus.RUNNING
