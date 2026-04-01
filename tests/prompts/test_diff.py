"""Tests for prompt diff engine: PromptDiff, diff_versions, diff_summary, has_semantic_change."""

from __future__ import annotations

from stronghold.prompts.diff import (
    DiffLine,
    PromptDiff,
    compute_diff,
    diff_summary,
    diff_versions,
    has_semantic_change,
)


# ── compute_diff (existing) ────────────────────────────────────────


class TestComputeDiff:
    def test_identical_content_no_diff(self) -> None:
        result = compute_diff("hello\n", "hello\n")
        assert result == []

    def test_added_line(self) -> None:
        result = compute_diff("line1\n", "line1\nline2\n")
        ops = [d.op for d in result]
        assert "add" in ops

    def test_removed_line(self) -> None:
        result = compute_diff("line1\nline2\n", "line1\n")
        ops = [d.op for d in result]
        assert "remove" in ops

    def test_modified_line(self) -> None:
        result = compute_diff("old text\n", "new text\n")
        ops = [d.op for d in result]
        assert "remove" in ops
        assert "add" in ops

    def test_headers_present(self) -> None:
        result = compute_diff("a\n", "b\n")
        headers = [d for d in result if d.op == "header"]
        assert len(headers) >= 2  # --- and +++ at minimum

    def test_context_lines(self) -> None:
        old = "ctx1\nctx2\nold\nctx3\nctx4\n"
        new = "ctx1\nctx2\nnew\nctx3\nctx4\n"
        result = compute_diff(old, new, context_lines=1)
        context = [d for d in result if d.op == "context"]
        assert len(context) >= 1

    def test_labels(self) -> None:
        result = compute_diff("a\n", "b\n", old_label="v1.0", new_label="v2.0")
        header_content = " ".join(d.content for d in result if d.op == "header")
        assert "v1.0" in header_content
        assert "v2.0" in header_content

    def test_line_numbers_tracked(self) -> None:
        result = compute_diff("a\nb\nc\n", "a\nx\nc\n")
        adds = [d for d in result if d.op == "add"]
        removes = [d for d in result if d.op == "remove"]
        for d in adds:
            assert d.new_lineno is not None
        for d in removes:
            assert d.old_lineno is not None

    def test_empty_to_content(self) -> None:
        result = compute_diff("", "new content\n")
        ops = [d.op for d in result]
        assert "add" in ops

    def test_diffline_frozen(self) -> None:
        d = DiffLine(op="add", content="test", new_lineno=1)
        assert d.op == "add"
        assert d.content == "test"

    def test_content_to_empty(self) -> None:
        result = compute_diff("existing content\n", "")
        ops = [d.op for d in result]
        assert "remove" in ops

    def test_multiline_diff(self) -> None:
        old = "line1\nline2\nline3\nline4\nline5\n"
        new = "line1\nchanged\nline3\nadded\nline4\nline5\n"
        result = compute_diff(old, new)
        adds = [d for d in result if d.op == "add"]
        removes = [d for d in result if d.op == "remove"]
        assert len(adds) >= 1
        assert len(removes) >= 1

    def test_default_labels(self) -> None:
        result = compute_diff("a\n", "b\n")
        header_content = " ".join(d.content for d in result if d.op == "header")
        assert "previous" in header_content
        assert "current" in header_content


# ── PromptDiff dataclass ────────────────────────────────────────────


class TestPromptDiff:
    def test_prompt_diff_fields(self) -> None:
        pd = PromptDiff(
            old_version=1,
            new_version=2,
            old_content="old",
            new_content="new",
            additions=3,
            deletions=1,
            diff_lines=["+added line", "-removed line"],
        )
        assert pd.old_version == 1
        assert pd.new_version == 2
        assert pd.old_content == "old"
        assert pd.new_content == "new"
        assert pd.additions == 3
        assert pd.deletions == 1
        assert len(pd.diff_lines) == 2

    def test_prompt_diff_frozen(self) -> None:
        pd = PromptDiff(
            old_version=1,
            new_version=2,
            old_content="a",
            new_content="b",
            additions=0,
            deletions=0,
            diff_lines=[],
        )
        try:
            pd.old_version = 5  # type: ignore[misc]
            raise AssertionError("Should not allow mutation")
        except AttributeError:
            pass  # frozen dataclass

    def test_prompt_diff_zero_counts(self) -> None:
        pd = PromptDiff(
            old_version=1,
            new_version=1,
            old_content="same",
            new_content="same",
            additions=0,
            deletions=0,
            diff_lines=[],
        )
        assert pd.additions == 0
        assert pd.deletions == 0
        assert pd.diff_lines == []


# ── diff_versions ───────────────────────────────────────────────────


class TestDiffVersions:
    def test_basic_diff(self) -> None:
        result = diff_versions("line1\nline2\n", "line1\nline3\n")
        assert isinstance(result, PromptDiff)
        assert result.additions >= 1
        assert result.deletions >= 1
        assert len(result.diff_lines) > 0

    def test_identical_content(self) -> None:
        result = diff_versions("same\n", "same\n")
        assert result.additions == 0
        assert result.deletions == 0
        assert result.diff_lines == []

    def test_only_additions(self) -> None:
        result = diff_versions("line1\n", "line1\nline2\nline3\n")
        assert result.additions == 2
        assert result.deletions == 0

    def test_only_deletions(self) -> None:
        result = diff_versions("line1\nline2\nline3\n", "line1\n")
        assert result.additions == 0
        assert result.deletions == 2

    def test_mixed_changes(self) -> None:
        old = "alpha\nbeta\ngamma\n"
        new = "alpha\nBETA\ngamma\ndelta\n"
        result = diff_versions(old, new)
        assert result.additions >= 1
        assert result.deletions >= 1

    def test_empty_to_content(self) -> None:
        result = diff_versions("", "new line\n")
        assert result.additions == 1
        assert result.deletions == 0

    def test_content_to_empty(self) -> None:
        result = diff_versions("old line\n", "")
        assert result.additions == 0
        assert result.deletions == 1

    def test_diff_lines_are_strings(self) -> None:
        result = diff_versions("a\n", "b\n")
        for line in result.diff_lines:
            assert isinstance(line, str)

    def test_diff_lines_contain_unified_format(self) -> None:
        result = diff_versions("old\n", "new\n")
        # Unified diff should contain +/- prefix lines
        has_plus = any(line.startswith("+") for line in result.diff_lines)
        has_minus = any(line.startswith("-") for line in result.diff_lines)
        assert has_plus
        assert has_minus

    def test_stores_old_and_new_content(self) -> None:
        result = diff_versions("old content\n", "new content\n")
        assert result.old_content == "old content\n"
        assert result.new_content == "new content\n"

    def test_version_numbers_default_zero(self) -> None:
        result = diff_versions("a\n", "b\n")
        assert result.old_version == 0
        assert result.new_version == 0

    def test_multiline_complex_diff(self) -> None:
        old = "header\nfoo\nbar\nbaz\nfooter\n"
        new = "header\nfoo\nQUX\nbaz\nextra\nfooter\n"
        result = diff_versions(old, new)
        # bar -> QUX (1 del + 1 add), plus 'extra' (1 add)
        assert result.additions >= 2
        assert result.deletions >= 1


# ── diff_summary ────────────────────────────────────────────────────


class TestDiffSummary:
    def test_summary_format(self) -> None:
        pd = PromptDiff(
            old_version=2,
            new_version=3,
            old_content="",
            new_content="",
            additions=5,
            deletions=2,
            diff_lines=[],
        )
        summary = diff_summary(pd)
        assert summary == "Version 2\u21923: +5 lines, -2 lines"

    def test_summary_zero_changes(self) -> None:
        pd = PromptDiff(
            old_version=1,
            new_version=2,
            old_content="",
            new_content="",
            additions=0,
            deletions=0,
            diff_lines=[],
        )
        summary = diff_summary(pd)
        assert summary == "Version 1\u21922: +0 lines, -0 lines"

    def test_summary_large_numbers(self) -> None:
        pd = PromptDiff(
            old_version=10,
            new_version=11,
            old_content="",
            new_content="",
            additions=100,
            deletions=50,
            diff_lines=[],
        )
        summary = diff_summary(pd)
        assert summary == "Version 10\u219211: +100 lines, -50 lines"

    def test_summary_only_additions(self) -> None:
        pd = PromptDiff(
            old_version=1,
            new_version=2,
            old_content="",
            new_content="",
            additions=3,
            deletions=0,
            diff_lines=[],
        )
        summary = diff_summary(pd)
        assert "+3 lines" in summary
        assert "-0 lines" in summary


# ── has_semantic_change ─────────────────────────────────────────────


class TestHasSemanticChange:
    def test_identical_strings(self) -> None:
        assert has_semantic_change("hello world", "hello world") is False

    def test_different_content(self) -> None:
        assert has_semantic_change("hello world", "goodbye world") is True

    def test_whitespace_normalization_spaces(self) -> None:
        assert has_semantic_change("hello   world", "hello world") is False

    def test_whitespace_normalization_tabs(self) -> None:
        assert has_semantic_change("hello\tworld", "hello world") is False

    def test_whitespace_normalization_leading_trailing(self) -> None:
        assert has_semantic_change("  hello world  ", "hello world") is False

    def test_whitespace_normalization_newlines(self) -> None:
        assert has_semantic_change("hello\n\n\nworld", "hello\nworld") is False

    def test_empty_strings(self) -> None:
        assert has_semantic_change("", "") is False

    def test_empty_vs_whitespace(self) -> None:
        assert has_semantic_change("", "   ") is False

    def test_real_content_change_with_whitespace(self) -> None:
        assert has_semantic_change("  foo  bar  ", "  foo  baz  ") is True

    def test_multiline_whitespace_only(self) -> None:
        old = "line1\n  line2\n\nline3\n"
        new = "line1\nline2\nline3\n"
        assert has_semantic_change(old, new) is False

    def test_multiline_real_change(self) -> None:
        old = "line1\nline2\nline3\n"
        new = "line1\nchanged\nline3\n"
        assert has_semantic_change(old, new) is True
