from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName


def test_mason_to_frank_loopback_is_persisted_and_resumable() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="implementation_ready",
        initial_worker=WorkerName.MASON,
    )

    orchestrator.advance_stage("run-1", "acceptance_defined", next_worker=WorkerName.FRANK)
    snapshot = orchestrator.dump_runs()

    restarted = BuildersOrchestrator()
    restarted.load_runs(snapshot)
    run = restarted.get_run("run-1")

    assert run.current_stage == "acceptance_defined"
    assert run.current_worker is WorkerName.FRANK
