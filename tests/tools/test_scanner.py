"""Tests for tools/scanner.py — good-first-issue detectors.

All detectors are pure functions over a Path layout; tests build tiny
fixture trees with tmp_path and assert on the returned suggestions.
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    root: Path,
    src_files: dict[str, str] | None = None,
    test_files: dict[str, str] | None = None,
    protocols: dict[str, str] | None = None,
    dashboard: dict[str, str] | None = None,
) -> Path:
    """Build a miniature src/tests layout mimicking the Stronghold repo."""
    (root / "src" / "stronghold").mkdir(parents=True)
    (root / "tests").mkdir()
    if protocols:
        proto_dir = root / "src" / "stronghold" / "protocols"
        proto_dir.mkdir()
        for name, content in protocols.items():
            (proto_dir / name).write_text(content)
    if src_files:
        for rel, content in src_files.items():
            p = root / "src" / "stronghold" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    if test_files:
        for rel, content in test_files.items():
            p = root / "tests" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    if dashboard:
        dash = root / "src" / "stronghold" / "dashboard"
        dash.mkdir()
        for name, content in dashboard.items():
            (dash / name).write_text(content)
    return root


# ---------------------------------------------------------------------------
# detect_missing_fakes
# ---------------------------------------------------------------------------


class TestDetectMissingFakes:
    def test_returns_empty_when_no_fakes_file(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            protocols={"llm.py": "class LLMClient(Protocol): ..."},
        )
        suggestions = detect_missing_fakes(
            root / "src" / "stronghold", root / "tests"
        )
        assert suggestions == []

    def test_returns_empty_when_no_protocols_dir(self, tmp_path: Path) -> None:
        root = _make_project(tmp_path, test_files={"fakes.py": ""})
        suggestions = detect_missing_fakes(
            root / "src" / "stronghold", root / "tests"
        )
        assert suggestions == []

    def test_flags_protocol_without_fake(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            test_files={"fakes.py": "# empty"},
            protocols={"llm.py": "class LLMClient(Protocol):\n    ..."},
        )
        suggestions = detect_missing_fakes(
            root / "src" / "stronghold", root / "tests"
        )
        assert len(suggestions) == 1
        s = suggestions[0]
        assert "FakeLLMClient" in s.title
        assert s.category == "missing_fake"

    def test_accepts_existing_fake(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            test_files={"fakes.py": "class FakeLLMClient: pass"},
            protocols={"llm.py": "class LLMClient(Protocol):\n    ..."},
        )
        suggestions = detect_missing_fakes(
            root / "src" / "stronghold", root / "tests"
        )
        assert suggestions == []

    def test_accepts_noop_prefix_alternative(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            test_files={"fakes.py": "class NoopLLMClient: pass"},
            protocols={"llm.py": "class LLMClient(Protocol):\n    ..."},
        )
        suggestions = detect_missing_fakes(
            root / "src" / "stronghold", root / "tests"
        )
        assert suggestions == []

    def test_skips_init_file(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            test_files={"fakes.py": ""},
            protocols={"__init__.py": "class Hidden(Protocol): ..."},
        )
        suggestions = detect_missing_fakes(
            root / "src" / "stronghold", root / "tests"
        )
        assert suggestions == []


# ---------------------------------------------------------------------------
# detect_missing_docstrings
# ---------------------------------------------------------------------------


def _long_module(with_docstring: bool) -> str:
    head = '"""Module docstring."""\n\n' if with_docstring else ""
    body = "\n".join(f"x = {i}" for i in range(30))
    return f"{head}from __future__ import annotations\n\n{body}\n"


class TestDetectMissingDocstrings:
    def test_flags_module_without_docstring(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={"big.py": _long_module(with_docstring=False)},
        )
        suggestions = detect_missing_docstrings(root / "src" / "stronghold")
        assert len(suggestions) == 1
        assert suggestions[0].category == "missing_docstring"
        assert "big.py" in suggestions[0].title

    def test_ignores_module_with_docstring(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={"big.py": _long_module(with_docstring=True)},
        )
        assert detect_missing_docstrings(root / "src" / "stronghold") == []

    def test_ignores_triple_single_quote_docstring(self, tmp_path: Path) -> None:
        body = "'''Triple single.'''\n\n" + "\n".join(f"x = {i}" for i in range(30))
        root = _make_project(tmp_path, src_files={"ok.py": body})
        assert detect_missing_docstrings(root / "src" / "stronghold") == []

    def test_ignores_short_modules(self, tmp_path: Path) -> None:
        """Modules under 20 lines are not worth the docstring warning."""
        short = "from __future__ import annotations\nx = 1\n"
        root = _make_project(tmp_path, src_files={"tiny.py": short})
        assert detect_missing_docstrings(root / "src" / "stronghold") == []

    def test_skips_init_files(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={"__init__.py": _long_module(with_docstring=False)},
        )
        assert detect_missing_docstrings(root / "src" / "stronghold") == []

    def test_future_import_before_docstring_is_acceptable(
        self, tmp_path: Path
    ) -> None:
        """`from __future__ import annotations` is skipped before the
        docstring check — a module with future import + docstring is OK."""
        content = (
            "from __future__ import annotations\n"
            '"""Module docstring."""\n'
            + "\n".join(f"x = {i}" for i in range(30))
            + "\n"
        )
        root = _make_project(tmp_path, src_files={"ok.py": content})
        assert detect_missing_docstrings(root / "src" / "stronghold") == []


# ---------------------------------------------------------------------------
# detect_sidebar_inconsistencies
# ---------------------------------------------------------------------------


class TestDetectSidebarInconsistencies:
    def test_no_dashboard_dir_returns_empty(self, tmp_path: Path) -> None:
        assert detect_sidebar_inconsistencies(tmp_path / "nope") == []

    def test_no_index_returns_empty(self, tmp_path: Path) -> None:
        dash = tmp_path / "dash"
        dash.mkdir()
        assert detect_sidebar_inconsistencies(dash) == []

    def test_consistent_sidebars_return_empty(self, tmp_path: Path) -> None:
        dash = tmp_path / "dash"
        dash.mkdir()
        links = '<a href="/dashboard/agents">A</a><a href="/greathall">G</a>'
        (dash / "index.html").write_text(links)
        (dash / "agents.html").write_text(links)
        assert detect_sidebar_inconsistencies(dash) == []

    def test_missing_link_flagged(self, tmp_path: Path) -> None:
        dash = tmp_path / "dash"
        dash.mkdir()
        (dash / "index.html").write_text(
            '<a href="/dashboard/agents">A</a><a href="/dashboard/runs">R</a>'
        )
        # agents.html is missing the /dashboard/runs link
        (dash / "agents.html").write_text('<a href="/dashboard/agents">A</a>')
        suggestions = detect_sidebar_inconsistencies(dash)
        assert len(suggestions) == 1
        assert "agents.html" in suggestions[0].description

    def test_login_and_index_excluded_from_scan(self, tmp_path: Path) -> None:
        dash = tmp_path / "dash"
        dash.mkdir()
        (dash / "index.html").write_text('<a href="/dashboard/x">X</a>')
        (dash / "login.html").write_text("")  # login excluded, no complaint
        assert detect_sidebar_inconsistencies(dash) == []


# ---------------------------------------------------------------------------
# detect_untested_modules
# ---------------------------------------------------------------------------


class TestDetectUntestedModules:
    def test_flags_module_without_test(self, tmp_path: Path) -> None:
        src_body = "\n".join(f"x = {i}" for i in range(25))
        root = _make_project(
            tmp_path,
            src_files={"mystery.py": src_body},
            test_files={"test_unrelated.py": "# no mention here"},
        )
        suggestions = detect_untested_modules(
            root / "src", root / "tests"
        )
        assert any(s.category == "untested_module" for s in suggestions)
        assert any("mystery" in s.title for s in suggestions)

    def test_skips_short_modules(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={"tiny.py": "x = 1\ny = 2\n"},
            test_files={},
        )
        suggestions = detect_untested_modules(
            root / "src", root / "tests"
        )
        assert [s for s in suggestions if "tiny" in s.title] == []

    def test_detects_test_file_that_imports_module(self, tmp_path: Path) -> None:
        src_body = "\n".join(f"x = {i}" for i in range(25))
        root = _make_project(
            tmp_path,
            src_files={"covered.py": src_body},
            test_files={"test_anything.py": "from stronghold.covered import x"},
        )
        suggestions = detect_untested_modules(
            root / "src", root / "tests"
        )
        # module_name 'covered' appears in the test file → found
        assert [s for s in suggestions if "covered" in s.title] == []

    def test_skips_init_py(self, tmp_path: Path) -> None:
        """__init__.py in the source tree must be skipped entirely."""
        # Create an __init__.py long enough to fail the length gate if reached.
        body = "\n".join(f"x = {i}" for i in range(30))
        (tmp_path / "src" / "stronghold").mkdir(parents=True)
        (tmp_path / "tests").mkdir()
        (tmp_path / "src" / "stronghold" / "__init__.py").write_text(body)
        suggestions = detect_untested_modules(
            tmp_path / "src", tmp_path / "tests"
        )
        assert [s for s in suggestions if "__init__" in s.title] == []

    def test_finds_test_at_direct_parts_path(self, tmp_path: Path) -> None:
        """If `tests/<parts>/test_<name>.py` exists directly, the module
        is considered covered without having to fall back to content grep."""
        body = "\n".join(f"x = {i}" for i in range(30))
        root = _make_project(
            tmp_path,
            src_files={"sub/mod.py": body},
            test_files={"sub/test_mod.py": "# stub covers mod"},
        )
        suggestions = detect_untested_modules(
            root / "src", root / "tests"
        )
        assert [s for s in suggestions if "mod" in s.title] == []

    def test_handles_undecodable_test_file_gracefully(
        self, tmp_path: Path
    ) -> None:
        """A binary / non-UTF-8 file in tests/ must not crash the scan —
        the except (OSError, UnicodeDecodeError) branch swallows it."""
        body = "\n".join(f"x = {i}" for i in range(30))
        root = _make_project(
            tmp_path,
            src_files={"lonely.py": body},
        )
        # Binary bytes that fail UTF-8 decode
        (root / "tests" / "binary_test.py").write_bytes(b"\xff\xfe\x00binary")
        suggestions = detect_untested_modules(
            root / "src", root / "tests"
        )
        # lonely.py should still be flagged as untested (binary file ignored)
        assert any("lonely" in s.title for s in suggestions)


# ---------------------------------------------------------------------------
# detect_todo_fixme
# ---------------------------------------------------------------------------


class TestDetectTodoFixme:
    def test_flags_todo_with_description(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={"a.py": "# TODO: wire this up properly later\nx = 1\n"},
        )
        suggestions = detect_todo_fixme(root / "src")
        assert len(suggestions) == 1
        s = suggestions[0]
        assert s.category == "todo_fixme"
        assert "TODO" in s.title

    def test_flags_fixme_and_hack_and_xxx(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={
                "a.py": (
                    "# FIXME: broken edge case on empty inputs\n"
                    "# HACK: works around upstream regression\n"
                    "# XXX: revisit after v1.0 ships\n"
                )
            },
        )
        suggestions = detect_todo_fixme(root / "src")
        # Title shape: "fix: resolve <TAG> in <file>:<line>"
        tags = {s.title.split("resolve ")[1].split(" ")[0] for s in suggestions}
        assert tags == {"FIXME", "HACK", "XXX"}

    def test_ignores_short_todo_descriptions(self, tmp_path: Path) -> None:
        """Descriptions under 10 chars are dropped — not actionable."""
        root = _make_project(
            tmp_path,
            src_files={"a.py": "# TODO: fix\n"},  # "fix" < 10 chars
        )
        assert detect_todo_fixme(root / "src") == []


# ---------------------------------------------------------------------------
# scan_for_good_first_issues — integration
# ---------------------------------------------------------------------------


class TestScanForGoodFirstIssues:
    def test_runs_all_detectors_and_returns_list(self, tmp_path: Path) -> None:
        root = _make_project(
            tmp_path,
            src_files={"a.py": "# TODO: something meaningful here\n"},
            test_files={"fakes.py": ""},
            protocols={"llm.py": "class LLMClient(Protocol):\n    ..."},
        )
        suggestions = scan_for_good_first_issues(root)
        # Should include at least the TODO + the missing fake
        categories = {s.category for s in suggestions}
        assert "todo_fixme" in categories
        assert "missing_fake" in categories

    def test_skips_detectors_when_dirs_absent(self, tmp_path: Path) -> None:
        """scan_for_good_first_issues gates each detector on dir existence."""
        # Only src/ exists, no tests/ or dashboard/
        (tmp_path / "src" / "stronghold").mkdir(parents=True)
        (tmp_path / "src" / "stronghold" / "a.py").write_text(
            "# TODO: legitimate long description here\n"
        )
        suggestions = scan_for_good_first_issues(tmp_path)
        # Only detectors that need just src/ should have run
        assert all(s.category in {"todo_fixme", "missing_docstring"} for s in suggestions)

    def test_empty_project_returns_empty(self, tmp_path: Path) -> None:
        assert scan_for_good_first_issues(tmp_path) == []

    def test_runs_dashboard_detector_when_dashboard_dir_exists(
        self, tmp_path: Path
    ) -> None:
        """The dashboard branch in scan_for_good_first_issues must fire
        when src/stronghold/dashboard/ exists."""
        root = _make_project(
            tmp_path,
            dashboard={
                "index.html": '<a href="/dashboard/agents">A</a><a href="/dashboard/runs">R</a>',
                "agents.html": '<a href="/dashboard/agents">A</a>',
            },
        )
        suggestions = scan_for_good_first_issues(root)
        # Sidebar inconsistency should be picked up by the integration runner.
        assert any(s.category == "sidebar_inconsistency" for s in suggestions)


# ---------------------------------------------------------------------------
# format_as_github_issue
# ---------------------------------------------------------------------------


class TestFormatAsGithubIssue:
    def test_builds_title_body_labels(self) -> None:
        s = IssueSuggestion(
            title="test: add SomeFake",
            category="missing_fake",
            files=("src/stronghold/protocols/llm.py", "tests/fakes.py"),
            description="short desc",
            what_youll_learn="something",
            acceptance_criteria=("one", "two"),
        )
        payload = format_as_github_issue(s)
        assert payload["title"] == "test: add SomeFake"
        assert payload["labels"] == ["good first issue"]
        body = str(payload["body"])
        assert "## Summary" in body
        assert "## Files" in body
        assert "- `src/stronghold/protocols/llm.py`" in body
        assert "- [ ] one" in body
        assert "- [ ] two" in body
        assert "## Scope" in body
        assert "small" in body
