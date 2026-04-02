from __future__ import annotations

from stronghold.builders import ArtifactRef, BuildersOrchestrator, RunResult, RunStatus, WorkerName


def test_replaying_same_runtime_result_does_not_corrupt_run_state() -> None:
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

    artifact = ArtifactRef(
        artifact_id="art_fixed",
        type="acceptance_criteria",
        path="runs/run-1/criteria.json",
        producer="frank",
    )
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="acceptance_defined",
        status=RunStatus.PASSED,
        summary="same result",
        artifacts=[artifact],
    )

    first = orchestrator.apply_result(result)
    second = orchestrator.apply_result(result)

    assert len(first.artifacts) == 1
    assert len(second.artifacts) == 1
    assert len(second.events) == len(first.events)
    assert second.current_stage == "acceptance_defined"
