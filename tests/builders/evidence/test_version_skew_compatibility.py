from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName


def test_core_can_route_new_runs_to_newest_ready_runtime_version() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.register_runtime_version("v1", state="ready")
    orchestrator.register_runtime_version("v2", state="ready")

    run = orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="queued",
        initial_worker=WorkerName.FRANK,
    )

    assert run.runtime_version == "v2"


def test_draining_runtime_does_not_receive_new_runs() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.register_runtime_version("v1", state="draining")
    orchestrator.register_runtime_version("v2", state="ready")

    run = orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="queued",
        initial_worker=WorkerName.FRANK,
    )

    assert run.runtime_version == "v2"
