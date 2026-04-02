from __future__ import annotations

from stronghold.builders import InMemoryGitHubService


def test_runtime_facing_github_interactions_flow_through_service_contract() -> None:
    github = InMemoryGitHubService()

    github.upsert_issue_update(
        run_id="run-1",
        issue_number=42,
        stage="implementation_started",
        body="Mason started",
    )
    pr = github.open_pr(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
        title="feat: issue 42",
        body="PR body",
    )

    assert github.list_issue_updates(run_id="run-1")[0].body == "Mason started"
    assert github.get_pr(pr.pr_number).title == "feat: issue 42"
