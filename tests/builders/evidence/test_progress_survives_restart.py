from __future__ import annotations

from stronghold.builders import InMemoryGitHubService


def test_progress_reporting_survives_restart_via_replayable_updates() -> None:
    github = InMemoryGitHubService()
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="acceptance_defined",
        body="Criteria ready",
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="implementation_started",
        body="Mason started",
    )
    persisted = github.list_issue_updates(run_id="run-1")

    restarted = InMemoryGitHubService()
    for update in persisted:
        restarted.upsert_issue_update(
            run_id=update.run_id,
            issue_number=update.issue_number,
            stage=update.stage,
            body=update.body,
        )

    assert [u.stage for u in restarted.list_issue_updates(run_id="run-1")] == [
        "acceptance_defined",
        "implementation_started",
    ]
