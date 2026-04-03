"""Tests for issue comment documentation system.

Evidence-based contracts:
- IssueCommentFormatter formats structured comments with headers
- Different comment types have appropriate formatting
- Error handling allows workflow to continue if commenting fails
- Comment content includes all required fields (step, status, details)
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, Mock

from stronghold.builders.nested_loop.comment_system import (
    IssueCommentFormatter,
    IssueCommentPublisher,
    CommentType,
)


class TestIssueCommentFormatter:
    """Formats workflow step documentation into GitHub issue comments."""

    def test_formats_frank_decomposition_comment(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.FRANK_DECOMPOSITION,
            step="problem_decomposition",
            details={
                "sub_problems": ["Problem 1", "Problem 2"],
                "assumptions": ["Assumption 1"],
            },
        )
        assert "## Problem Decomposition" in comment
        assert "### Sub-problems" in comment
        assert "Problem 1" in comment
        assert "Problem 2" in comment
        assert "### Assumptions" in comment
        assert "Assumption 1" in comment

    def test_formats_mason_test_results_comment(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.MASON_TEST_RESULTS,
            step="test_execution",
            details={
                "passing": 45,
                "failing": 5,
                "coverage": "92%",
                "high_water_mark": 45,
            },
        )
        assert "## Mason Test Results" in comment
        assert "Passing: 45" in comment
        assert "Failing: 5" in comment
        assert "Coverage: 92%" in comment
        assert "High Water Mark: 45" in comment

    def test_formats_quality_check_comment(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.QUALITY_CHECKS,
            step="quality_verification",
            details={
                "pytest": "passed",
                "ruff_check": "passed",
                "mypy": "passed",
                "bandit": "passed",
                "coverage": "95%",
            },
        )
        assert "## Quality Checks" in comment
        assert "pytest: passed" in comment
        assert "ruff_check: passed" in comment
        assert "mypy: passed" in comment
        assert "bandit: passed" in comment
        assert "Coverage: 95%" in comment

    def test_formats_pr_creation_comment(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.PR_CREATED,
            step="pr_creation",
            details={
                "pr_number": 123,
                "pr_url": "https://github.com/org/repo/pull/123",
                "branch": "builders/42-abc123",
            },
        )
        assert "## Pull Request Created" in comment
        assert "PR #123" in comment
        assert "https://github.com/org/repo/pull/123" in comment
        assert "Branch: builders/42-abc123" in comment

    def test_formats_failure_comment(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.OUTER_LOOP_FAILURE,
            step="outer_retry",
            details={
                "retry_count": 2,
                "error_reason": "Mason failed to improve after 10 attempts",
                "model_used": "mistral-large",
            },
        )
        assert "## Outer Loop Failure" in comment
        assert "Retry Count: 2" in comment
        assert "Error: Mason failed to improve after 10 attempts" in comment
        assert "Model Used: mistral-large" in comment

    def test_formats_admin_signaling_comment(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.ADMIN_SIGNAL,
            step="admin_alert",
            details={
                "total_failures": 5,
                "recommendation": "Review issue complexity and consider manual intervention",
            },
        )
        assert "## Admin Attention Required" in comment
        assert "Total Failures: 5" in comment
        assert "Recommendation:" in comment

    def test_includes_timestamp_in_all_comments(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.FRANK_DECOMPOSITION,
            step="test_step",
            details={},
        )
        assert "Timestamp:" in comment

    def test_includes_run_id_in_all_comments(self) -> None:
        formatter = IssueCommentFormatter()
        comment = formatter.format_comment(
            comment_type=CommentType.FRANK_DECOMPOSITION,
            step="test_step",
            details={},
            run_id="run-abc123",
        )
        assert "Run ID: run-abc123" in comment


class TestIssueCommentPublisher:
    """Publishes formatted comments to GitHub issues with error handling."""

    async def test_publishes_comment_via_github_tool(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = (
            '{"id": 999, "url": "https://github.com/org/repo/issues/42#issuecomment-999"}'
        )

        publisher = IssueCommentPublisher(tool_dispatcher=mock_tool_dispatcher)
        await publisher.publish_comment(
            owner="org",
            repo="repo",
            issue_number=42,
            comment_body="## Test Comment\nContent here",
        )

        mock_tool_dispatcher.execute.assert_called_once()
        call_args = mock_tool_dispatcher.execute.call_args
        assert call_args[0][0] == "github"
        assert call_args[0][1]["action"] == "post_pr_comment"
        assert call_args[0][1]["owner"] == "org"
        assert call_args[0][1]["repo"] == "repo"
        assert call_args[0][1]["issue_number"] == 42
        assert "Test Comment" in call_args[0][1]["body"]

    async def test_continues_on_github_tool_error(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = "Error: API rate limit exceeded"

        publisher = IssueCommentPublisher(tool_dispatcher=mock_tool_dispatcher)
        await publisher.publish_comment(
            owner="org",
            repo="repo",
            issue_number=42,
            comment_body="## Test Comment",
        )

        mock_tool_dispatcher.execute.assert_called_once()

    async def test_formats_and_publishes_complete_comment(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = '{"id": 999}'

        formatter = IssueCommentFormatter()
        publisher = IssueCommentPublisher(
            tool_dispatcher=mock_tool_dispatcher,
            formatter=formatter,
        )
        await publisher.publish_workflow_step(
            owner="org",
            repo="repo",
            issue_number=42,
            comment_type=CommentType.MASON_TEST_RESULTS,
            step="test_execution",
            details={"passing": 100, "failing": 0},
            run_id="run-xyz",
        )

        mock_tool_dispatcher.execute.assert_called_once()
        call_args = mock_tool_dispatcher.execute.call_args
        comment_body = call_args[0][1]["body"]
        assert "## Mason Test Results" in comment_body
        assert "Run ID: run-xyz" in comment_body

    async def test_returns_success_true_on_successful_publish(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = '{"id": 999}'

        publisher = IssueCommentPublisher(tool_dispatcher=mock_tool_dispatcher)
        result = await publisher.publish_comment(
            owner="org",
            repo="repo",
            issue_number=42,
            comment_body="Test",
        )

        assert result.success is True
        assert result.comment_id == 999

    async def test_returns_success_false_on_github_error(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = "Error: unauthorized"

        publisher = IssueCommentPublisher(tool_dispatcher=mock_tool_dispatcher)
        result = await publisher.publish_comment(
            owner="org",
            repo="repo",
            issue_number=42,
            comment_body="Test",
        )

        assert result.success is False
        assert result.comment_id is None

    async def test_handles_json_parse_error_gracefully(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = "Not valid JSON"

        publisher = IssueCommentPublisher(tool_dispatcher=mock_tool_dispatcher)
        result = await publisher.publish_comment(
            owner="org",
            repo="repo",
            issue_number=42,
            comment_body="Test",
        )

        assert result.success is False
