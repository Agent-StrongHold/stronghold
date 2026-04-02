from __future__ import annotations

import pytest

from stronghold.builders import BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_stage_dispatch_is_role_and_stage_specific() -> None:
    runtime = BuildersRuntime()

    async def handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary=f"{request.worker.value}:{request.stage}",
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", handler)

    assert runtime.supports(WorkerName.FRANK, "acceptance_defined")
    assert not runtime.supports(WorkerName.FRANK, "implementation_started")
    assert not runtime.supports(WorkerName.MASON, "acceptance_defined")

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

    assert result.summary == "frank:acceptance_defined"


@pytest.mark.asyncio
async def test_unsupported_role_stage_fails_cleanly() -> None:
    runtime = BuildersRuntime()

    result = await runtime.execute(
        RunRequest(
            run_id="run-1",
            worker=WorkerName.MASON,
            stage="acceptance_defined",
            repo="org/repo",
            issue_number=42,
            branch="b",
            workspace_ref="ws",
        )
    )

    assert result.status is RunStatus.FAILED
    assert "Unsupported role/stage" in result.summary
