from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, WorkerName


def test_coverage_gate_is_threshold_based_and_deterministic() -> None:
    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="quality_checks_passed",
        initial_worker=WorkerName.MASON,
    )

    assert not orchestrator.can_complete(
        "run-1",
        ci_passed=True,
        coverage_pct=84.99,
        quality_passed=True,
    )
    assert orchestrator.can_complete(
        "run-1",
        ci_passed=True,
        coverage_pct=85.0,
        quality_passed=True,
    )
