"""Tests for the codebase scanner (good-first-issue detector)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

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


@pytest.fixture
def project() -> Path:
    """Create a minimal synthetic project for scanning."""
    root = Path(tempfile.mkdtemp())
    (root / "src" / "stronghold" / "protocols").mkdir(parents=True)
    (root / "src" / "stronghold" / "dashboard").mkdir(parents=True)
    (root / "tests").mkdir()
    return root


# ── detect_missing_fakes ────────────────────────────────────────────


def test_missing_fakes_finds_protocol_without_fake(project: Path) -> None:
    (project / "src" / "stronghold" / "protocols" / "widget.py").write_text(
        "from typing import Protocol\nclass WidgetStore(Protocol):\n    def get(self): ...\n"
    )
    (project / "tests" / "fakes.py").write_text("class FakeOtherThing: pass\n")
    result = detect_missing_fakes(project / "src" / "stronghold", project / "tests")
    assert len(result) >= 1
    assert any("WidgetStore" in s.title or "widget" in s.description.lower() for s in result)


def test_missing_fakes_no_fakes_file(project: Path) -> None:
    """Scanner returns empty list (not crash) when tests/fakes.py doesn't exist."""
    result = detect_missing_fakes(project / "src" / "stronghold", project / "tests")
    assert result == []


def test_missing_fakes_no_protocols_dir(project: Path) -> None:
    (project / "tests" / "fakes.py").write_text("")
    # Remove protocols dir
    import shutil
    shutil.rmtree(project / "src" / "stronghold" / "protocols")
    result = detect_missing_fakes(project / "src" / "stronghold", project / "tests")
    assert result == []


def test_missing_fakes_detects_fake_present(project: Path) -> None:
    (project / "src" / "stronghold" / "protocols" / "thing.py").write_text(
        "from typing import Protocol\nclass ThingStore(Protocol):\n    def a(self): ...\n"
    )
    (project / "tests" / "fakes.py").write_text("class FakeThingStore:\n    def a(self): pass\n")
    result = detect_missing_fakes(project / "src" / "stronghold", project / "tests")
    # ThingStore has a fake so should not be in results
    assert not any("ThingStore" in s.title for s in result)


# ── detect_missing_docstrings ───────────────────────────────────────


def test_missing_docstrings_flags_long_module(project: Path) -> None:
    # Long enough (>20 lines), no docstring
    content = "\n".join(["x = 1"] * 25)
    (project / "src" / "stronghold" / "nodoc.py").write_text(content)
    result = detect_missing_docstrings(project / "src")
    assert any("nodoc" in s.title for s in result)


def test_missing_docstrings_ignores_short_module(project: Path) -> None:
    (project / "src" / "stronghold" / "tiny.py").write_text("x = 1\n")
    result = detect_missing_docstrings(project / "src")
    assert not any("tiny" in s.title for s in result)


def test_missing_docstrings_accepts_future_import_first(project: Path) -> None:
    """Module with future import + docstring should NOT be flagged."""
    content = (
        'from __future__ import annotations\n'
        '"""Module docstring."""\n'
        + "\n".join(["x = 1"] * 25)
    )
    (project / "src" / "stronghold" / "good.py").write_text(content)
    result = detect_missing_docstrings(project / "src")
    assert not any("good" in s.title for s in result)


def test_missing_docstrings_ignores_init(project: Path) -> None:
    (project / "src" / "stronghold" / "__init__.py").write_text("\n".join(["x=1"] * 25))
    result = detect_missing_docstrings(project / "src")
    assert not any("__init__" in s.title for s in result)


# ── detect_sidebar_inconsistencies ──────────────────────────────────


def test_sidebar_no_index_returns_empty(project: Path) -> None:
    result = detect_sidebar_inconsistencies(project / "src" / "stronghold" / "dashboard")
    assert result == []


def test_sidebar_missing_dashboard_dir() -> None:
    result = detect_sidebar_inconsistencies(Path("/nonexistent/dashboard"))
    assert result == []


def test_sidebar_all_consistent(project: Path) -> None:
    dash = project / "src" / "stronghold" / "dashboard"
    index_html = '<a href="/dashboard/a">A</a><a href="/dashboard/b">B</a>'
    (dash / "index.html").write_text(index_html)
    (dash / "page2.html").write_text(index_html)
    result = detect_sidebar_inconsistencies(dash)
    assert result == []


def test_sidebar_inconsistent_detected(project: Path) -> None:
    dash = project / "src" / "stronghold" / "dashboard"
    (dash / "index.html").write_text('<a href="/dashboard/a">A</a><a href="/dashboard/b">B</a>')
    (dash / "page2.html").write_text('<a href="/dashboard/a">A</a>')  # missing /dashboard/b
    result = detect_sidebar_inconsistencies(dash)
    assert len(result) == 1
    assert "page2.html" in result[0].description


# ── detect_untested_modules ─────────────────────────────────────────


def test_untested_module_flagged(project: Path) -> None:
    content = "\n".join(["x = 1"] * 25)
    (project / "src" / "stronghold" / "lonely.py").write_text(content)
    result = detect_untested_modules(project / "src", project / "tests")
    assert any("lonely" in s.title for s in result)


def test_untested_module_with_test_file(project: Path) -> None:
    (project / "src" / "stronghold" / "thing.py").write_text("\n".join(["x=1"] * 25))
    (project / "tests" / "test_thing.py").write_text("def test_x(): pass\n")
    result = detect_untested_modules(project / "src", project / "tests")
    assert not any("thing" in s.title for s in result)


def test_untested_module_with_test_import(project: Path) -> None:
    (project / "src" / "stronghold" / "imported.py").write_text("\n".join(["x=1"] * 25))
    (project / "tests" / "test_other.py").write_text(
        "from stronghold.imported import x\ndef test_y(): pass\n"
    )
    result = detect_untested_modules(project / "src", project / "tests")
    assert not any(s.title == "test: add tests for imported" for s in result)


def test_untested_module_skips_small_files(project: Path) -> None:
    (project / "src" / "stronghold" / "tiny.py").write_text("x=1\n")  # <20 lines
    result = detect_untested_modules(project / "src", project / "tests")
    assert not any("tiny" in s.title for s in result)


# ── detect_todo_fixme ───────────────────────────────────────────────


def test_detect_todo_comment(project: Path) -> None:
    (project / "src" / "stronghold" / "todo.py").write_text(
        "# TODO: refactor this terrible function into something sensible\n"
        "x = 1\n"
    )
    result = detect_todo_fixme(project / "src")
    assert len(result) == 1
    assert "TODO" in result[0].title


def test_detect_fixme_comment(project: Path) -> None:
    (project / "src" / "stronghold" / "fix.py").write_text(
        "# FIXME: this breaks under concurrent writes with more than ten workers\n"
    )
    result = detect_todo_fixme(project / "src")
    assert any("FIXME" in s.title for s in result)


def test_short_todo_ignored(project: Path) -> None:
    """TODO with short description is skipped (< 10 chars)."""
    (project / "src" / "stronghold" / "short.py").write_text("# TODO: x\n")
    result = detect_todo_fixme(project / "src")
    assert not any("short.py" in s.title for s in result)


# ── scan_for_good_first_issues (orchestrator) ───────────────────────


def test_scan_empty_project(project: Path) -> None:
    """Scanner handles empty but valid project."""
    (project / "tests" / "fakes.py").write_text("")
    result = scan_for_good_first_issues(project)
    assert isinstance(result, list)


def test_scan_runs_all_detectors(project: Path) -> None:
    # One TODO
    (project / "src" / "stronghold" / "t.py").write_text(
        "# TODO: fix this very broken thing properly\nx=1\n"
    )
    # Missing-docstring module
    (project / "src" / "stronghold" / "nodoc.py").write_text("\n".join(["x=1"] * 25))
    (project / "tests" / "fakes.py").write_text("")
    result = scan_for_good_first_issues(project)
    categories = {s.category for s in result}
    assert "todo_fixme" in categories
    # Untested module or missing docstring
    assert "untested_module" in categories or "missing_docstring" in categories


def test_scan_no_src_dir(project: Path) -> None:
    import shutil
    shutil.rmtree(project / "src")
    (project / "tests" / "fakes.py").write_text("")
    result = scan_for_good_first_issues(project)
    assert result == []


# ── format_as_github_issue ──────────────────────────────────────────


def test_format_as_github_issue_structure() -> None:
    s = IssueSuggestion(
        title="test: add tests for foo",
        category="untested_module",
        files=("src/foo.py",),
        description="Foo has no tests",
        what_youll_learn="how foo works",
        acceptance_criteria=("has tests", "tests pass"),
        estimated_scope="small",
    )
    payload = format_as_github_issue(s)
    assert payload["title"] == "test: add tests for foo"
    assert "good first issue" in payload["labels"]
    body = str(payload["body"])
    assert "## Summary" in body
    assert "Foo has no tests" in body
    assert "## Files" in body
    assert "src/foo.py" in body
    assert "## Acceptance criteria" in body
    assert "- [ ] has tests" in body
    assert "- [ ] tests pass" in body
    assert "small" in body
