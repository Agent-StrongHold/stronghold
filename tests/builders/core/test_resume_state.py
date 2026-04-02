from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName


def test_core_resumes_persisted_run_with_retries_and_runtime_version() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.register_runtime_version("v2", state="ready")
    run = orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="implementation_started",
        initial_worker=WorkerName.MASON,
        runtime_version="v2",
    )
    orchestrator.schedule_retry("run-1", reason="first failure")

    snapshot = orchestrator.dump_runs()
    restarted = BuildersOrchestrator()
    restarted.load_runs(snapshot)
    loaded = restarted.get_run("run-1")

    assert loaded.runtime_version == "v2"
    assert loaded.retries["implementation_started"] == 1
    assert loaded.current_worker is WorkerName.MASON
