from __future__ import annotations

from stronghold.builders import RunRequest, WorkerName


def test_unknown_context_fields_do_not_break_contract() -> None:
    request = RunRequest(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="acceptance_defined",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        context={"future_field": "allowed"},
    )

    assert request.context["future_field"] == "allowed"
