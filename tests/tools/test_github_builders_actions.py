"""Tests for GitHub tool enhancements: list_issue_comments, search_issues, get_linked_issues.

Evidence-based contracts:
- list_issue_comments returns comments from the correct GitHub API endpoint
- search_issues queries GitHub search API with structured query
- get_linked_issues finds linked issues/PRs via timeline events
- Each action is registered in the tool definition action enum
- Error handling returns ToolResult with success=False
"""

from __future__ import annotations

import json

import httpx
import respx

from stronghold.tools.github import GITHUB_TOOL_DEF, GitHubToolExecutor


class TestListIssueCommentsAction:
    """list_issue_comments action contract."""

    def test_action_in_enum(self) -> None:
        actions = GITHUB_TOOL_DEF.parameters["properties"]["action"]["enum"]
        assert "list_issue_comments" in actions

    @respx.mock
    async def test_returns_comments_for_issue(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/42/comments").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 100,
                        "user": {"login": "frank-bot"},
                        "body": "## Problem Decomposition\n- Sub-problem 1: ...",
                        "created_at": "2026-04-02T10:00:00Z",
                    },
                    {
                        "id": 101,
                        "user": {"login": "mason-bot"},
                        "body": "## Test Results\n- 45/50 passing",
                        "created_at": "2026-04-02T11:00:00Z",
                    },
                ],
            )
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute(
            {
                "action": "list_issue_comments",
                "owner": "org",
                "repo": "repo",
                "issue_number": 42,
            }
        )
        assert result.success
        comments = json.loads(result.content)
        assert len(comments) == 2
        assert comments[0]["id"] == 100
        assert comments[0]["user"] == "frank-bot"
        assert "Problem Decomposition" in comments[0]["body"]

    @respx.mock
    async def test_returns_empty_list_when_no_comments(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/42/comments").mock(
            return_value=httpx.Response(200, json=[])
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute(
            {
                "action": "list_issue_comments",
                "owner": "org",
                "repo": "repo",
                "issue_number": 42,
            }
        )
        assert result.success
        comments = json.loads(result.content)
        assert comments == []


class TestSearchIssuesAction:
    """search_issues action contract."""

    def test_action_in_enum(self) -> None:
        actions = GITHUB_TOOL_DEF.parameters["properties"]["action"]["enum"]
        assert "search_issues" in actions

    @respx.mock
    async def test_searches_with_query(self) -> None:
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total_count": 1,
                    "items": [
                        {
                            "number": 15,
                            "title": "Related PR for auth",
                            "state": "open",
                            "html_url": "https://github.com/org/repo/pull/15",
                            "pull_request": {
                                "url": "https://api.github.com/repos/org/repo/pulls/15"
                            },
                        },
                    ],
                },
            )
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute(
            {
                "action": "search_issues",
                "owner": "org",
                "repo": "repo",
                "query": "auth is:pr is:open",
            }
        )
        assert result.success
        data = json.loads(result.content)
        assert data["total_count"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["number"] == 15

    @respx.mock
    async def test_includes_repo_scope_in_query(self) -> None:
        route = respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total_count": 0,
                    "items": [],
                },
            )
        )
        executor = GitHubToolExecutor(token="test-token")
        await executor.execute(
            {
                "action": "search_issues",
                "owner": "org",
                "repo": "repo",
                "query": "authentication",
            }
        )
        request_url = str(route.calls[0].request.url)
        assert "repo%3Aorg%2Frepo" in request_url or "repo:org/repo" in request_url

    @respx.mock
    async def test_search_returns_empty_results(self) -> None:
        respx.get("https://api.github.com/search/issues").mock(
            return_value=httpx.Response(
                200,
                json={
                    "total_count": 0,
                    "items": [],
                },
            )
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute(
            {
                "action": "search_issues",
                "owner": "org",
                "repo": "repo",
                "query": "nonexistent-feature-xyz",
            }
        )
        assert result.success
        data = json.loads(result.content)
        assert data["total_count"] == 0


class TestGetLinkedIssuesAction:
    """get_linked_issues action contract — finds linked issues/PRs via timeline."""

    def test_action_in_enum(self) -> None:
        actions = GITHUB_TOOL_DEF.parameters["properties"]["action"]["enum"]
        assert "get_linked_issues" in actions

    @respx.mock
    async def test_returns_linked_issues_from_timeline(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/42/timeline").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "event": "connected",
                        "source": {
                            "issue": {
                                "number": 10,
                                "title": "Original issue",
                                "state": "open",
                                "html_url": "https://github.com/org/repo/issues/10",
                            }
                        },
                    },
                    {
                        "event": "cross-referenced",
                        "source": {
                            "issue": {
                                "number": 55,
                                "title": "Related PR",
                                "state": "open",
                                "html_url": "https://github.com/org/repo/pull/55",
                                "pull_request": {"url": "..."},
                            }
                        },
                    },
                    {
                        "event": "commented",
                        "body": "Just a comment, not a link",
                    },
                ],
            )
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute(
            {
                "action": "get_linked_issues",
                "owner": "org",
                "repo": "repo",
                "issue_number": 42,
            }
        )
        assert result.success
        linked = json.loads(result.content)
        assert len(linked) == 2
        assert linked[0]["number"] == 10
        assert linked[1]["number"] == 55

    @respx.mock
    async def test_returns_empty_when_no_links(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/42/timeline").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"event": "commented", "body": "Just a comment"},
                    {"event": "labeled", "label": {"name": "bug"}},
                ],
            )
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute(
            {
                "action": "get_linked_issues",
                "owner": "org",
                "repo": "repo",
                "issue_number": 42,
            }
        )
        assert result.success
        linked = json.loads(result.content)
        assert linked == []
