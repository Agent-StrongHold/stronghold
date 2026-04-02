from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName


def test_persisted_run_state_survives_core_restart() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="issue_analyzed",
        initial_worker=WorkerName.FRANK,
    )
    orchestrator.advance_stage("run-1", "acceptance_defined")

    snapshot = orchestrator.dump_runs()

    restarted = BuildersOrchestrator()
    restarted.load_runs(snapshot)
    run = restarted.get_run("run-1")

    assert run.current_stage == "acceptance_defined"
    assert run.issue_number == 42
    assert run.current_worker is WorkerName.FRANK
