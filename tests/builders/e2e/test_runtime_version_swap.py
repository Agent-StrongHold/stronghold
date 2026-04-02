from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName


def test_core_can_drain_old_runtime_while_new_runs_hit_new_runtime() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.register_runtime_version("v1", state="ready")

    old_run = orchestrator.create_run(
        run_id="run-old",
        repo="org/repo",
        issue_number=41,
        branch="builders/41-run",
        workspace_ref="ws-old",
        initial_stage="implementation_started",
        initial_worker=WorkerName.MASON,
    )

    orchestrator.register_runtime_version("v2", state="ready")
    orchestrator.set_runtime_state("v1", "draining")

    new_run = orchestrator.create_run(
        run_id="run-new",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run",
        workspace_ref="ws-new",
        initial_stage="queued",
        initial_worker=WorkerName.FRANK,
    )

    assert old_run.runtime_version == "v1"
    assert new_run.runtime_version == "v2"
    assert orchestrator.active_runs_for_version("v1") == 1

    orchestrator.advance_stage("run-old", "implementation_ready")
    orchestrator.advance_stage("run-old", "quality_checks_passed")
    completed = orchestrator.advance_stage("run-old", "completed")

    assert completed.status is RunStatus.PASSED
    assert orchestrator.active_runs_for_version("v1") == 0
