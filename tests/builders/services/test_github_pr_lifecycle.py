from __future__ import annotations

from stronghold.builders import InMemoryGitHubService


def test_pr_lifecycle_operations_are_deterministic() -> None:
    github = InMemoryGitHubService()

    pr = github.open_pr(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
        title="feat: issue 42",
        body="Initial PR body",
    )
    updated = github.update_pr(pr.pr_number, body="Updated PR body")
    fetched = github.get_pr(pr.pr_number)

    assert pr.pr_number == 1
    assert updated.pr_number == pr.pr_number
    assert fetched.body == "Updated PR body"
    assert fetched.branch == "builders/42-run-1"
