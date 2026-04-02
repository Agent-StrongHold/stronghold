from __future__ import annotations

from stronghold.builders import RunResult, RunStatus, WorkerName


def test_run_result_captures_status_and_optional_lists() -> None:
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.MASON,
        stage="implementation_started",
        status=RunStatus.PASSED,
        summary="implemented",
    )

    assert result.status is RunStatus.PASSED
    assert result.claims == []
    assert result.logs == []
