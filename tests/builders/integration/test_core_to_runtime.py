from __future__ import annotations

import pytest

from stronghold.builders import BuildersOrchestrator, BuildersRuntime, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_core_builds_typed_request_and_runtime_executes_it() -> None:
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
            summary="acceptance artifact created",
        )

    runtime.register(WorkerName.FRANK, "acceptance_defined", frank_handler)

    request = orchestrator.build_request("run-1")
    result = await runtime.execute(request)

    assert request.run_id == "run-1"
    assert request.worker is WorkerName.FRANK
    assert request.stage == "acceptance_defined"
    assert result.status is RunStatus.PASSED
    assert result.summary == "acceptance artifact created"
