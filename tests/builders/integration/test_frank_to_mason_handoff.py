from __future__ import annotations

import pytest

from stronghold.builders import (
    ArtifactRef,
    BuildersOrchestrator,
    BuildersRuntime,
    RunResult,
    RunStatus,
    WorkerName,
)


@pytest.mark.asyncio
async def test_frank_outputs_become_mason_inputs_through_artifacts_only() -> None:
    orchestrator = BuildersOrchestrator()
    runtime = BuildersRuntime()

    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="acceptance_defined",
        initial_worker=WorkerName.FRANK,
    )

    async def frank_handler(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="frank produced acceptance bundle",
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
        artifact_types = [artifact.type for artifact in request.artifacts]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary=",".join(sorted(artifact_types)),
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", frank_handler)
    runtime.register(WorkerName.MASON, "implementation_started", mason_handler)

    frank_request = orchestrator.build_request("run-1")
    frank_result = await runtime.execute(frank_request)
    orchestrator.apply_result(frank_result, next_stage="tests_written")
    orchestrator.advance_stage("run-1", "implementation_started", next_worker=WorkerName.MASON)

    mason_request = orchestrator.build_request("run-1")
    mason_result = await runtime.execute(mason_request)

    assert [artifact.type for artifact in mason_request.artifacts] == [
        "acceptance_criteria",
        "test_plan",
    ]
    assert mason_result.summary == "acceptance_criteria,test_plan"
