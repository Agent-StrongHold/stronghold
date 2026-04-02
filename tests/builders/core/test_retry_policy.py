from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName


def test_core_retries_are_counted_per_stage() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="implementation_started",
        initial_worker=WorkerName.MASON,
    )

    orchestrator.schedule_retry("run-1", reason="flake")
    assert orchestrator.get_run("run-1").retries["implementation_started"] == 1

    second = orchestrator.schedule_retry("run-1", reason="still red")
    assert second.retries["implementation_started"] == 2
    assert second.status is RunStatus.RUNNING
    assert second.events[-1].event == "retry_scheduled"
