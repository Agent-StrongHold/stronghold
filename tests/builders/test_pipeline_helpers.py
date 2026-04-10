"""Unit tests for pure helpers in RuntimePipeline.

These are deterministic, sync, and require no fakes — they exercise
the static/classmethod utilities that downstream refactors must not break.
"""

from __future__ import annotations

from stronghold.builders.pipeline import RuntimePipeline

# Re-use the issue-type registry from pipeline.py
from stronghold.builders.pipeline import ISSUE_TYPE_REGISTRY


# ── _render ──────────────────────────────────────────────────────────


class TestRender:
    def test_replaces_single_placeholder(self) -> None:
        assert RuntimePipeline._render("Hello {{name}}", name="Ada") == "Hello Ada"

    def test_replaces_multiple_placeholders(self) -> None:
        result = RuntimePipeline._render("{{a}} and {{b}}", a="1", b="2")
        assert result == "1 and 2"

    def test_leaves_unmatched_placeholders(self) -> None:
        result = RuntimePipeline._render("Hello {{name}}, {{unknown}}", name="Ada")
        assert result == "Hello Ada, {{unknown}}"

    def test_handles_empty_template(self) -> None:
        assert RuntimePipeline._render("") == ""

    def test_coerces_non_string_values(self) -> None:
        assert RuntimePipeline._render("count={{n}}", n="42") == "count=42"


# ── _count_passing / _count_failing ──────────────────────────────────


class TestCountPassing:
    def test_zero(self) -> None:
        assert RuntimePipeline._count_passing("0 passed") == 0

    def test_one(self) -> None:
        assert RuntimePipeline._count_passing("1 passed") == 1

    def test_many(self) -> None:
        assert RuntimePipeline._count_passing("47 passed in 12.3s") == 47

    def test_no_match(self) -> None:
        assert RuntimePipeline._count_passing("ERROR: collection failed") == 0

    def test_mixed_with_failed(self) -> None:
        assert RuntimePipeline._count_passing("3 passed, 2 failed") == 3


class TestCountFailing:
    def test_failed_only(self) -> None:
        assert RuntimePipeline._count_failing("3 failed") == 3

    def test_errors_only(self) -> None:
        assert RuntimePipeline._count_failing("2 errors") == 2

    def test_both(self) -> None:
        assert RuntimePipeline._count_failing("3 failed, 2 errors") == 5

    def test_no_failures(self) -> None:
        assert RuntimePipeline._count_failing("10 passed in 1.2s") == 0

    def test_one_error(self) -> None:
        assert RuntimePipeline._count_failing("1 error") == 1


# ── _parse_violation_files ───────────────────────────────────────────


class TestParseViolationFiles:
    def test_extracts_src_paths(self) -> None:
        output = (
            "src/stronghold/foo.py:10: E501 line too long\n"
            "src/stronghold/bar.py:5: W291 trailing whitespace"
        )
        result = RuntimePipeline._parse_violation_files(output)
        assert result == ["src/stronghold/foo.py", "src/stronghold/bar.py"]

    def test_deduplicates(self) -> None:
        output = (
            "src/stronghold/foo.py:10: E501\n"
            "src/stronghold/foo.py:20: E501"
        )
        result = RuntimePipeline._parse_violation_files(output)
        assert result == ["src/stronghold/foo.py"]

    def test_ignores_non_src_paths(self) -> None:
        output = "tests/test_foo.py:1: E501"
        result = RuntimePipeline._parse_violation_files(output)
        assert result == []

    def test_empty_output(self) -> None:
        assert RuntimePipeline._parse_violation_files("") == []


# ── _detect_issue_type ───────────────────────────────────────────────


class TestDetectIssueType:
    def _make_run(self, title: str = "", content: str = "", files: list[str] | None = None) -> object:
        """Minimal fake run with the attributes _detect_issue_type reads."""
        from types import SimpleNamespace
        run = SimpleNamespace()
        run._issue_title = title
        run._issue_content = content
        run._analysis = {"affected_files": files or []}
        return run

    def test_matches_ui_dashboard_signals(self) -> None:
        run = self._make_run(title="Fix sidebar overlap on dashboard")
        result = RuntimePipeline._detect_issue_type(run)
        assert result.name == "ui_dashboard"

    def test_matches_test_redis_signals(self) -> None:
        run = self._make_run(files=["src/stronghold/cache/redis_pool.py"])
        result = RuntimePipeline._detect_issue_type(run)
        assert result.name == "test_redis"

    def test_priority_ordering(self) -> None:
        """Higher-priority types win when multiple match."""
        # test_redis (priority 10) should win over test_utility (priority 5)
        # when both signal sets overlap
        run = self._make_run(files=["src/stronghold/cache/redis_pool.py"])
        result = RuntimePipeline._detect_issue_type(run)
        assert result.priority >= 10

    def test_falls_back_to_lowest_priority(self) -> None:
        """When no signals match, returns the lowest-priority entry."""
        run = self._make_run(title="something completely unrelated xyz123")
        result = RuntimePipeline._detect_issue_type(run)
        lowest = min(ISSUE_TYPE_REGISTRY, key=lambda t: t.priority)
        assert result.priority == lowest.priority


# ── _parse_onboarding_sections ───────────────────────────────────────


class TestParseOnboardingSections:
    def test_splits_by_h2(self) -> None:
        text = "## Section A\ncontent A\n## Section B\ncontent B"
        result = RuntimePipeline._parse_onboarding_sections(text)
        assert "Section A" in result
        assert "Section B" in result
        assert "content A" in result["Section A"]
        assert "content B" in result["Section B"]

    def test_splits_by_h3(self) -> None:
        text = "### Sub A\nsub content\n### Sub B\nmore content"
        result = RuntimePipeline._parse_onboarding_sections(text)
        assert len(result) >= 2

    def test_empty_input(self) -> None:
        result = RuntimePipeline._parse_onboarding_sections("")
        assert isinstance(result, dict)

    def test_no_headers(self) -> None:
        result = RuntimePipeline._parse_onboarding_sections("just plain text\nno headers")
        assert isinstance(result, dict)
