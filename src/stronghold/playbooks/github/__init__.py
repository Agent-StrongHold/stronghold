"""GitHub playbooks — agent-oriented replacements for the github(action=…) tool.

Each playbook composes several GitHub API calls server-side and returns a
Brief. The first landed here is `review_pull_request`; others (merge_pr,
triage_issues, open_pr, respond_to_issue, list_repo_activity) land in
subsequent phases.
"""

from __future__ import annotations

from stronghold.playbooks.github.review_pull_request import (
    ReviewPullRequestPlaybook,
    review_pull_request,
)

__all__ = ["ReviewPullRequestPlaybook", "review_pull_request"]
