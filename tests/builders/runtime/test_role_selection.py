from __future__ import annotations

import pytest

from stronghold.builders import BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_shared_runtime_routes_to_registered_role_handler() -> None:
    runtime = BuildersRuntime()

    async def frank_handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="frank handled stage",
        )

    async def mason_handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="mason handled stage",
        )

    async def auditor_handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="auditor handled stage",
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", frank_handler)
    runtime.register(WorkerName.MASON, "implementation_started", mason_handler)
    runtime.register(WorkerName.AUDITOR, "pr_audit", auditor_handler)

    frank_result = await runtime.execute(
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
    mason_result = await runtime.execute(
        RunRequest(
            run_id="run-1",
            worker=WorkerName.MASON,
            stage="implementation_started",
            repo="org/repo",
            issue_number=42,
            branch="b",
            workspace_ref="ws",
        )
    )
    auditor_result = await runtime.execute(
        RunRequest(
            run_id="run-1",
            worker=WorkerName.AUDITOR,
            stage="pr_audit",
            repo="org/repo",
            issue_number=42,
            branch="b",
            workspace_ref="ws",
        )
    )

    assert frank_result.summary == "frank handled stage"
    assert mason_result.summary == "mason handled stage"
    assert auditor_result.summary == "auditor handled stage"
