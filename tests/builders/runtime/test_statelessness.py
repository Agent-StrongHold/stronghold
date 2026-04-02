from __future__ import annotations

import pytest

from stronghold.builders import BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_runtime_does_not_mutate_request_or_store_run_state() -> None:
    runtime = BuildersRuntime()

    async def handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="ok",
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", handler)

    request = RunRequest(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="acceptance_defined",
        repo="org/repo",
        issue_number=42,
        branch="b",
        workspace_ref="ws",
        context={"attempt": 1},
    )

    result_one = await runtime.execute(request)
    result_two = await runtime.execute(request)

    assert result_one.summary == "ok"
    assert result_two.summary == "ok"
    assert request.context == {"attempt": 1}
    assert not hasattr(runtime, "_runs")
