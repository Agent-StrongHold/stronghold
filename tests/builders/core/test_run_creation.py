from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName


def test_run_creation_persists_initial_state() -> None:
    orchestrator = BuildersOrchestrator()

    run = orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
    )

    assert run.run_id == "run-1"
    assert run.repo == "org/repo"
    assert run.issue_number == 42
    assert run.current_stage == "queued"
    assert run.current_worker is WorkerName.FRANK
    assert run.status is RunStatus.QUEUED
    assert run.events[-1].event == "run_created"


def test_build_request_uses_core_owned_state() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="issue_analyzed",
        initial_worker=WorkerName.MASON,
    )

    request = orchestrator.build_request("run-1")

    assert request.run_id == "run-1"
    assert request.stage == "issue_analyzed"
    assert request.worker is WorkerName.MASON
    assert request.workspace_ref == "ws-1"
