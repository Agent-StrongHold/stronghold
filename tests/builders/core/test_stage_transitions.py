from __future__ import annotations

import pytest

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName


def test_stage_transitions_are_controlled_by_core() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
    )

    run = orchestrator.advance_stage("run-1", "issue_analyzed", next_worker=WorkerName.FRANK)
    assert run.current_stage == "issue_analyzed"
    assert run.status is RunStatus.RUNNING

    run = orchestrator.advance_stage("run-1", "acceptance_defined", next_worker=WorkerName.FRANK)
    assert run.current_stage == "acceptance_defined"

    run = orchestrator.advance_stage("run-1", "tests_written", next_worker=WorkerName.MASON)
    assert run.current_stage == "tests_written"
    assert run.current_worker is WorkerName.MASON


def test_invalid_stage_transition_is_rejected() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
    )

    with pytest.raises(ValueError, match="invalid stage transition"):
        orchestrator.advance_stage("run-1", "completed")
