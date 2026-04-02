from __future__ import annotations

import pytest

from stronghold.builders import ArtifactRef, BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_runtime_emits_typed_artifacts_for_stage_handlers() -> None:
    runtime = BuildersRuntime()

    async def frank_handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="bundle",
            artifacts=[
                ArtifactRef(
                    type="acceptance_criteria",
                    path="runs/run-1/criteria.json",
                    producer="frank",
                )
            ],
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", frank_handler)
    result = await runtime.execute(
        RunRequest(
            run_id="run-1",
            worker=WorkerName.FRANK,
            stage="acceptance_defined",
            repo="org/repo",
            issue_number=42,
            branch="b",
            workspace_ref="ws",
        )
    )

    assert result.artifacts[0].type == "acceptance_criteria"
    assert result.artifacts[0].producer == "frank"
