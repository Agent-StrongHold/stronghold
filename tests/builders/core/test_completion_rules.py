from __future__ import annotations

import pytest

from stronghold.builders import BuildersOrchestrator, RunStatus, WorkerName


def test_completion_requires_quality_ci_and_coverage() -> None:
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
        ci_passed=False,
        coverage_pct=90.0,
        quality_passed=True,
    )
    assert not orchestrator.can_complete(
        "run-1",
        ci_passed=True,
        coverage_pct=84.9,
        quality_passed=True,
    )
    assert orchestrator.can_complete(
        "run-1",
        ci_passed=True,
        coverage_pct=85.0,
        quality_passed=True,
    )


def test_completion_fails_when_gates_not_satisfied() -> None:
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

    with pytest.raises(ValueError, match="completion gates not satisfied"):
        orchestrator.complete_run_if_ready(
            "run-1",
            ci_passed=True,
            coverage_pct=70.0,
            quality_passed=True,
        )

    completed = orchestrator.complete_run_if_ready(
        "run-1",
        ci_passed=True,
        coverage_pct=90.0,
        quality_passed=True,
    )
    assert completed.status is RunStatus.PASSED
