from __future__ import annotations

from stronghold.builders import WorkerName, WorkerStatus


def test_worker_status_reports_capabilities() -> None:
    status = WorkerStatus(
        worker=WorkerName.AUDITOR,
        version="0.1.0",
        status="ready",
        capabilities=["pr_audit", "rework_feedback"],
    )

    assert status.worker is WorkerName.AUDITOR
    assert "pr_audit" in status.capabilities
