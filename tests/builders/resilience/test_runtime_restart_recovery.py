from __future__ import annotations

import pytest

from stronghold.builders import BuildersOrchestrator, BuildersRuntime, RunRequest, RunResult, RunStatus, WorkerName


@pytest.mark.asyncio
async def test_runs_survive_builders_runtime_restart() -> None:
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

    async def frank_handler(request: RunRequest) -> RunResult:
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="frank complete",
        )

    runtime_one = BuildersRuntime()
    runtime_one.register(WorkerName.FRANK, "acceptance_defined", frank_handler)
    result = await runtime_one.execute(orchestrator.build_request("run-1"))
    orchestrator.apply_result(result, next_stage="tests_written")

    runtime_two = BuildersRuntime()

    assert orchestrator.get_run("run-1").current_stage == "tests_written"
    assert not runtime_two.supports(WorkerName.FRANK, "acceptance_defined")
