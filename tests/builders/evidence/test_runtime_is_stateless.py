from __future__ import annotations

import pytest

from stronghold.builders import BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_runtime_has_no_durable_run_registry() -> None:
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
    await runtime.execute(
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

    assert not hasattr(runtime, "_runs")
    assert sorted(runtime._handlers.keys()) == [WorkerName.FRANK]
