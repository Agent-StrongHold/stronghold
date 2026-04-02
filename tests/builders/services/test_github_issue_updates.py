from __future__ import annotations

from stronghold.builders import InMemoryGitHubService


def test_issue_progress_updates_are_stage_aware_and_replay_safe() -> None:
    github = InMemoryGitHubService()

    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="acceptance_defined",
        body="Acceptance criteria ready",
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="acceptance_defined",
        body="Acceptance criteria revised",
    )
    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="implementation_started",
        body="Implementation started",
    )

    updates = github.list_issue_updates(run_id="run-1")

    assert len(updates) == 2
    assert updates[0].stage == "acceptance_defined"
    assert updates[0].body == "Acceptance criteria revised"
    assert updates[1].stage == "implementation_started"
