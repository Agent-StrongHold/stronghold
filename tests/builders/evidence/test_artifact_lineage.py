from __future__ import annotations

from stronghold.builders import ArtifactRef, BuildersOrchestrator, RunResult, RunStatus, WorkerName


def test_artifact_lineage_persists_across_stage_progression() -> None:
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

    criteria = ArtifactRef(
        artifact_id="art_criteria",
        type="acceptance_criteria",
        path="runs/run-1/criteria.json",
        producer="frank",
        metadata={"target": "mason"},
    )
    test_plan = ArtifactRef(
        artifact_id="art_test_plan",
        type="test_plan",
        path="runs/run-1/test-plan.json",
        producer="frank",
        metadata={"target": "mason"},
    )

    orchestrator.apply_result(
        RunResult(
            run_id="run-1",
            worker=WorkerName.FRANK,
            stage="acceptance_defined",
            status=RunStatus.PASSED,
            summary="frank bundle",
            artifacts=[criteria, test_plan],
        ),
        next_stage="tests_written",
    )
    orchestrator.advance_stage("run-1", "implementation_started", next_worker=WorkerName.MASON)

    run = orchestrator.get_run("run-1")

    assert [artifact.artifact_id for artifact in run.artifacts] == [
        "art_criteria",
        "art_test_plan",
    ]
    assert run.artifacts[0].metadata["target"] == "mason"
