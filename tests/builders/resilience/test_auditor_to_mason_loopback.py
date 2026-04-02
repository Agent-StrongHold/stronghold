from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName


def test_auditor_to_mason_loopback_is_durable() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="implementation_ready",
        initial_worker=WorkerName.AUDITOR,
    )

    orchestrator.advance_stage("run-1", "implementation_started", next_worker=WorkerName.MASON)
    snapshot = orchestrator.dump_runs()

    restarted = BuildersOrchestrator()
    restarted.load_runs(snapshot)
    run = restarted.get_run("run-1")

    assert run.current_stage == "implementation_started"
    assert run.current_worker is WorkerName.MASON
