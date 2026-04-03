"""Tests for Mason codebase scanner — good-first-issue detector.

Uses tmp_path for filesystem fixtures. No mocks.
"""

from __future__ import annotations

from pathlib import Path

from stronghold.tools.scanner import (
    IssueSuggestion,
    detect_missing_docstrings,
    detect_missing_fakes,
    detect_sidebar_inconsistencies,
    detect_todo_fixme,
    detect_untested_modules,
    format_as_github_issue,
    scan_for_good_first_issues,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestDetectMissingFakes:
    """Find protocols without fakes."""

    def test_detects_missing_fake(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "protocols" / "memory.py",
            "from typing import Protocol\n\nclass LearningStore(Protocol):\n    pass\n",
        )
        _write(tmp_path / "fakes.py", "class FakeLLMClient:\n    pass\n")

        results = detect_missing_fakes(tmp_path, tmp_path)
        assert len(results) == 1
        assert "FakeLearningStore" in results[0].title

    def test_existing_fake_not_flagged(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "protocols" / "llm.py",
            "from typing import Protocol\n\nclass LLMClient(Protocol):\n    pass\n",
        )
        _write(tmp_path / "fakes.py", "class FakeLLMClient:\n    pass\n")

        results = detect_missing_fakes(tmp_path, tmp_path)
        assert len(results) == 0

    def test_noop_variant_accepted(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "protocols" / "tracing.py",
            "from typing import Protocol\n\nclass TracingBackend(Protocol):\n    pass\n",
        )
        _write(tmp_path / "fakes.py", "class NoopTracingBackend:\n    pass\n")

        results = detect_missing_fakes(tmp_path, tmp_path)
        assert len(results) == 0

    def test_skips_init(self, tmp_path: Path) -> None:
        _write(tmp_path / "protocols" / "__init__.py", "")
        _write(tmp_path / "fakes.py", "")
        results = detect_missing_fakes(tmp_path, tmp_path)
        assert len(results) == 0


class TestDetectMissingDocstrings:
    """Find modules without docstrings."""

    def test_detects_missing_docstring(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        content = "from __future__ import annotations\n" + "x = 1\n" * 25
        _write(src_dir / "router" / "scorer.py", content)

        results = detect_missing_docstrings(src_dir)
        assert len(results) == 1
        assert "scorer" in results[0].title

    def test_has_docstring_not_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        content = '"""Router scoring logic."""\n' + "x = 1\n" * 25
        _write(src_dir / "router" / "scorer.py", content)

        results = detect_missing_docstrings(src_dir)
        assert len(results) == 0

    def test_short_files_skipped(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        _write(src_dir / "tiny.py", "x = 1\n")

        results = detect_missing_docstrings(src_dir)
        assert len(results) == 0


class TestDetectSidebarInconsistencies:
    """Find dashboard pages with mismatched sidebars."""

    def test_detects_missing_link(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "index.html",
            '<a href="/greathall">Hall</a><a href="/dashboard/mason">Workshop</a>',
        )
        _write(tmp_path / "agents.html", '<a href="/greathall">Hall</a>')

        results = detect_sidebar_inconsistencies(tmp_path)
        assert len(results) == 1
        assert "agents.html" in results[0].description

    def test_consistent_not_flagged(self, tmp_path: Path) -> None:
        nav = '<a href="/greathall">Hall</a><a href="/dashboard/agents">Knights</a>'
        _write(tmp_path / "index.html", nav)
        _write(tmp_path / "agents.html", nav)

        results = detect_sidebar_inconsistencies(tmp_path)
        assert len(results) == 0


class TestDetectTodoFixme:
    """Find TODO/FIXME comments."""

    def test_detects_todo(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "router.py",
            "# TODO: add fallback scoring when all models are exhausted\nx = 1\n",
        )
        results = detect_todo_fixme(tmp_path)
        assert len(results) == 1
        assert "TODO" in results[0].title

    def test_detects_fixme(self, tmp_path: Path) -> None:
        _write(
            tmp_path / "auth.py",
            "# FIXME: token refresh not implemented yet\nx = 1\n",
        )
        results = detect_todo_fixme(tmp_path)
        assert len(results) == 1

    def test_short_comments_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path / "foo.py", "# TODO: fix\n")
        results = detect_todo_fixme(tmp_path)
        assert len(results) == 0

    def test_no_todos_clean(self, tmp_path: Path) -> None:
        _write(tmp_path / "clean.py", "x = 1\n")
        results = detect_todo_fixme(tmp_path)
        assert len(results) == 0


class TestDetectUntestedModules:
    """Find source modules without test coverage."""

    def test_detects_untested(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "stronghold"
        tests = tmp_path / "tests"
        _write(src / "router" / "scorer.py", "class Scorer:\n" + "    pass\n" * 20)
        _write(tests / "conftest.py", "")

        results = detect_untested_modules(tmp_path / "src", tests)
        assert len(results) >= 1
        assert any("scorer" in r.title for r in results)

    def test_tested_module_not_flagged(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "stronghold"
        tests = tmp_path / "tests"
        _write(src / "router" / "scorer.py", "class Scorer:\n" + "    pass\n" * 20)
        _write(tests / "router" / "test_scorer.py", "import scorer\n")

        results = detect_untested_modules(tmp_path / "src", tests)
        # Should not flag scorer since test_scorer.py exists
        assert not any("scorer" in r.title for r in results)


class TestFormatAsGithubIssue:
    """Issue formatting."""

    def test_includes_all_sections(self) -> None:
        suggestion = IssueSuggestion(
            title="test: add FakeRouter to fakes.py",
            category="missing_fake",
            files=("src/stronghold/protocols/router.py",),
            description="Router protocol has no fake.",
            what_youll_learn="How the router works.",
            acceptance_criteria=("Fake exists", "Tests pass"),
        )
        payload = format_as_github_issue(suggestion)
        assert payload["title"] == "test: add FakeRouter to fakes.py"
        assert "good first issue" in payload["labels"]
        assert "## What you'll learn" in payload["body"]
        assert "- [ ] Fake exists" in payload["body"]


class TestScanForGoodFirstIssues:
    """Full scan integration."""

    def test_runs_all_detectors(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "stronghold"
        tests = tmp_path / "tests"
        _write(
            src / "protocols" / "new.py",
            "from typing import Protocol\n\nclass NewThing(Protocol):\n    pass\n",
        )
        _write(tests / "fakes.py", "")
        _write(src / "dashboard" / "index.html", '<a href="/greathall">Hall</a>')

        results = scan_for_good_first_issues(tmp_path)
        assert len(results) >= 1
        categories = {r.category for r in results}
        assert "missing_fake" in categories

    def test_empty_project_returns_empty(self, tmp_path: Path) -> None:
        results = scan_for_good_first_issues(tmp_path)
        assert results == []
