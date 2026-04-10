"""Unit tests for the extracted OnboardingContext module."""

from __future__ import annotations

from types import SimpleNamespace

from stronghold.builders.pipeline.context import OnboardingContext


def _make_run(title: str = "", content: str = "", files: list[str] | None = None) -> SimpleNamespace:
    run = SimpleNamespace()
    run._issue_title = title
    run._issue_content = content
    run._analysis = {"affected_files": files or []}
    return run


class TestDetectIssueType:
    def test_matches_ui_signals(self) -> None:
        run = _make_run(title="Fix sidebar overlap on dashboard")
        result = OnboardingContext.detect_issue_type(run)
        assert result.name == "ui_dashboard"

    def test_matches_redis_signals(self) -> None:
        run = _make_run(files=["src/stronghold/cache/redis_pool.py"])
        result = OnboardingContext.detect_issue_type(run)
        assert result.name == "test_redis"

    def test_falls_back_without_crash(self) -> None:
        run = _make_run(title="something completely unrelated xyz123")
        result = OnboardingContext.detect_issue_type(run)
        assert result is not None
        assert hasattr(result, "name")


class TestParseSections:
    def test_h2(self) -> None:
        text = "## A\ncontent A\n## B\ncontent B"
        result = OnboardingContext.parse_sections(text)
        assert "A" in result
        assert "B" in result

    def test_empty(self) -> None:
        assert OnboardingContext.parse_sections("") == {}
