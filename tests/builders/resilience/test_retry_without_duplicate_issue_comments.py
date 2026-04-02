from __future__ import annotations

from stronghold.builders import InMemoryGitHubService


def test_retries_do_not_spam_duplicate_issue_comments() -> None:
    github = InMemoryGitHubService()
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="implementation_started",
        body="Mason started",
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="implementation_started",
        body="Mason started again",
    )

    updates = github.list_issue_updates(run_id="run-1")
    assert len(updates) == 1
    assert updates[0].body == "Mason started again"
