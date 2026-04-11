"""Evidence-based tests for Bug 6: Mason hallucinates test import paths.

v0.9 plan item 8b. Mason's impl stage sometimes writes test files that
import ``from stronghold.X.Y import Z`` where ``stronghold.X.Y`` doesn't
exist, or where the symbol was never defined. The test then crashes at
collection time and pollutes CI.

Fix: ``check_test_imports_exist(diff_lines, *, file_path, repo_root)``
is a pure-function auditor check that follows the existing convention
in ``src/stronghold/agents/auditor/checks.py``::

    def check_X(diff_lines: list[str], *, file_path: str) -> list[ReviewFinding]

Behaviour the test suite locks in:

  - Only scans added lines (prefix ``+``) in files under ``tests/`` or
    named ``test_*.py``. Production files are out of scope.
  - Resolves ``stronghold.a.b.c`` against ``src/stronghold/a/b/c.py`` or
    ``src/stronghold/a/b/c/__init__.py`` under the given ``repo_root``.
  - Ignores stdlib, third-party, and relative imports entirely.
  - Dedupes per-module so repeated bad imports produce one finding.
  - Is wired into ``stronghold.agents.auditor.ALL_CHECKS``.
  - Handles syntax errors / unusual whitespace / alias forms without
    crashing.

All tests originally FAILED on red because the function did not exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stronghold.agents.auditor.checks import check_test_imports_exist
from stronghold.types.feedback import Severity, ViolationCategory

REAL_MODULE = "stronghold.api.litellm_client"  # verified exists
FAKE_MODULE = "stronghold.builders.pipeline"   # verified does NOT exist


def _added(lines: list[str]) -> list[str]:
    """Decorate lines as added hunks in a unified diff."""
    return [f"+{line}" for line in lines]


@pytest.fixture
def repo_root() -> Path:
    """Absolute repo root so the check's filesystem resolver is deterministic
    regardless of the pytest cwd."""
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# File-scope gating
# ---------------------------------------------------------------------------


class TestFileScope:
    def test_skips_non_test_file(self, repo_root: Path) -> None:
        """A production file with a bogus import is out of scope."""
        diff = _added([f"from {FAKE_MODULE} import Foo"])
        findings = check_test_imports_exist(
            diff, file_path="src/stronghold/foo.py", repo_root=repo_root
        )
        assert findings == []

    def test_applies_to_test_prefix_at_tests_root(self, repo_root: Path) -> None:
        diff = _added([f"from {FAKE_MODULE} import Foo"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_thing.py", repo_root=repo_root
        )
        assert len(findings) == 1

    def test_applies_to_nested_tests_dir(self, repo_root: Path) -> None:
        diff = _added([f"from {FAKE_MODULE} import Foo"])
        findings = check_test_imports_exist(
            diff, file_path="tests/unit/api/test_thing.py", repo_root=repo_root
        )
        assert len(findings) == 1

    def test_applies_to_helper_under_tests_without_prefix(
        self, repo_root: Path
    ) -> None:
        """A helper file under tests/ (without test_ prefix) is still a
        test-scope file and MUST be scanned — this is where the classic
        'tests/helpers/fakes.py imports a nonexistent module' bug hides."""
        diff = _added([f"from {FAKE_MODULE} import Foo"])
        findings = check_test_imports_exist(
            diff, file_path="tests/helpers/assertion_helpers.py", repo_root=repo_root
        )
        assert len(findings) == 1

    def test_empty_file_path_returns_empty(self, repo_root: Path) -> None:
        diff = _added([f"from {FAKE_MODULE} import Foo"])
        findings = check_test_imports_exist(
            diff, file_path="", repo_root=repo_root
        )
        assert findings == []


# ---------------------------------------------------------------------------
# Hallucination detection
# ---------------------------------------------------------------------------


class TestHallucinationDetection:
    def test_flags_nonexistent_stronghold_module(self, repo_root: Path) -> None:
        """Core evidence: importing a module that does not exist."""
        diff = _added([f"from {FAKE_MODULE} import RuntimePipeline"])
        findings = check_test_imports_exist(
            diff, file_path="tests/builders/test_thing.py", repo_root=repo_root
        )
        assert len(findings) == 1
        f = findings[0]
        assert f.category == ViolationCategory.HALLUCINATED_IMPORT
        assert f.severity == Severity.HIGH
        assert FAKE_MODULE in f.description
        assert f.file_path == "tests/builders/test_thing.py"

    def test_passes_existing_stronghold_module_file(self, repo_root: Path) -> None:
        """stronghold.api.litellm_client resolves to a .py file."""
        diff = _added([f"from {REAL_MODULE} import LiteLLMClient"])
        findings = check_test_imports_exist(
            diff, file_path="tests/api/test_thing.py", repo_root=repo_root
        )
        assert findings == []

    def test_passes_existing_stronghold_package(self, repo_root: Path) -> None:
        """stronghold.agents.auditor resolves to a __init__.py package."""
        diff = _added(["from stronghold.agents.auditor import check_mock_usage"])
        findings = check_test_imports_exist(
            diff, file_path="tests/agents/auditor/test_thing.py", repo_root=repo_root
        )
        assert findings == []

    def test_flags_bare_import_of_nonexistent_module(
        self, repo_root: Path
    ) -> None:
        diff = _added([f"import {FAKE_MODULE}"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_bare.py", repo_root=repo_root
        )
        assert len(findings) == 1

    def test_flags_bare_import_with_alias(self, repo_root: Path) -> None:
        diff = _added([f"import {FAKE_MODULE} as pipeline"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_alias.py", repo_root=repo_root
        )
        assert len(findings) == 1

    def test_multiple_bad_imports_dedupe_per_module(
        self, repo_root: Path
    ) -> None:
        """Two bad modules → two findings. Same bad module twice → one."""
        diff = _added(
            [
                f"from {FAKE_MODULE} import A",
                f"from {FAKE_MODULE} import B",  # duplicate module
                "from stronghold.nope.nada import C",  # different bad module
                f"from {REAL_MODULE} import LiteLLMClient",  # good
            ]
        )
        findings = check_test_imports_exist(
            diff, file_path="tests/test_multi.py", repo_root=repo_root
        )
        assert len(findings) == 2
        modules = {f.description.split("`")[1] for f in findings}
        assert modules == {FAKE_MODULE, "stronghold.nope.nada"}

    def test_deeply_nested_nonexistent_module_flagged(
        self, repo_root: Path
    ) -> None:
        diff = _added(["from stronghold.a.b.c.d.e import Thing"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_deep.py", repo_root=repo_root
        )
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# Ignored categories — stdlib, third-party, relative, context/removal
# ---------------------------------------------------------------------------


class TestIgnoredImports:
    def test_stdlib_imports_ignored(self, repo_root: Path) -> None:
        diff = _added(["import os", "import json", "from pathlib import Path"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_std.py", repo_root=repo_root
        )
        assert findings == []

    def test_third_party_imports_ignored(self, repo_root: Path) -> None:
        diff = _added(
            ["import httpx", "import pytest", "from pydantic import BaseModel"]
        )
        findings = check_test_imports_exist(
            diff, file_path="tests/test_third.py", repo_root=repo_root
        )
        assert findings == []

    def test_relative_imports_ignored(self, repo_root: Path) -> None:
        """Relative imports are test-file-local; not our concern."""
        diff = _added(
            ["from .fakes import FakeClient", "from ..conftest import fixture_x"]
        )
        findings = check_test_imports_exist(
            diff, file_path="tests/test_rel.py", repo_root=repo_root
        )
        assert findings == []

    def test_bare_stronghold_without_submodule_ignored(
        self, repo_root: Path
    ) -> None:
        """`from stronghold import X` targets the package itself, which
        always exists — no need to flag."""
        diff = _added(["from stronghold import __version__"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_top.py", repo_root=repo_root
        )
        assert findings == []

    def test_ignores_removed_and_context_lines(self, repo_root: Path) -> None:
        """Only added lines (`+`) are scanned. Removals and context are
        pre-existing and out of scope."""
        diff = [
            f"-from {FAKE_MODULE} import Gone",
            f" from {FAKE_MODULE} import StillThere",
            f"-import {FAKE_MODULE}",
        ]
        findings = check_test_imports_exist(
            diff, file_path="tests/test_ctx.py", repo_root=repo_root
        )
        assert findings == []

    def test_ignores_commented_imports(self, repo_root: Path) -> None:
        """A `+` line whose content is a comment must not match."""
        diff = _added([f"# from {FAKE_MODULE} import X"])
        findings = check_test_imports_exist(
            diff, file_path="tests/test_comm.py", repo_root=repo_root
        )
        assert findings == []


# ---------------------------------------------------------------------------
# Robustness
# ---------------------------------------------------------------------------


class TestRobustness:
    def test_empty_diff_returns_empty_list(self, repo_root: Path) -> None:
        assert (
            check_test_imports_exist(
                [], file_path="tests/test_empty.py", repo_root=repo_root
            )
            == []
        )

    def test_whitespace_variation_still_detected(self, repo_root: Path) -> None:
        """Extra whitespace / tabs between tokens must not hide the
        import from the regex."""
        diff = [
            f"+from   {FAKE_MODULE}   import   X",
            f"+\tfrom {FAKE_MODULE}.other import Y",
        ]
        findings = check_test_imports_exist(
            diff, file_path="tests/test_ws.py", repo_root=repo_root
        )
        assert len(findings) == 2

    def test_non_python_diff_does_not_crash(self, repo_root: Path) -> None:
        """YAML / JSON noise in the diff must be ignored, not crash."""
        diff = _added(
            [
                "  key: value",
                '{"a": 1}',
                "random text with `from foo import bar` inside",
            ]
        )
        findings = check_test_imports_exist(
            diff, file_path="tests/test_noise.py", repo_root=repo_root
        )
        assert findings == []

    def test_partial_matches_not_flagged(self, repo_root: Path) -> None:
        """A line mentioning `stronghold.x` in a string literal is not
        an import and must not be flagged."""
        diff = _added(
            [
                '    url = "stronghold.nope.nada"',
                "    # see stronghold.builders.pipeline for context",
            ]
        )
        findings = check_test_imports_exist(
            diff, file_path="tests/test_literal.py", repo_root=repo_root
        )
        assert findings == []

    def test_default_repo_root_is_cwd(self, tmp_path: Path) -> None:
        """When repo_root is None the check falls back to the module-level
        default (_DEFAULT_REPO_ROOT captured at import time) or cwd. The
        important property is that it does not crash."""
        diff = _added([f"from {FAKE_MODULE} import X"])
        findings = check_test_imports_exist(diff, file_path="tests/test_default.py")
        # Without repo_root the check may or may not find the fake module
        # depending on where cwd points — just assert it didn't crash and
        # returned a list.
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# Dispatcher wiring — dead code prevention
# ---------------------------------------------------------------------------


class TestDispatcherWiring:
    def test_check_is_importable_from_public_checks_module(self) -> None:
        from stronghold.agents.auditor import checks as checks_mod

        assert hasattr(checks_mod, "check_test_imports_exist"), (
            "new check must be exposed on the auditor.checks module"
        )

    def test_check_is_in_all_checks_registry(self) -> None:
        """The canonical wire-in point is `ALL_CHECKS` on the auditor
        package. Anything not in this tuple is dead code."""
        from stronghold.agents.auditor import ALL_CHECKS

        assert check_test_imports_exist in ALL_CHECKS

    def test_check_exported_via_package_init(self) -> None:
        """Re-export from the package __init__ so consumers can do
        `from stronghold.agents.auditor import check_test_imports_exist`."""
        from stronghold.agents import auditor

        assert hasattr(auditor, "check_test_imports_exist")
        assert auditor.check_test_imports_exist is check_test_imports_exist

    def test_check_is_referenced_outside_checks_module(self) -> None:
        """A grep-level belt-and-suspenders: at least one file under
        ``stronghold/agents/auditor/`` other than ``checks.py`` must
        mention the new check by name. Catches the case where somebody
        adds the function but forgets every wiring step."""
        import stronghold.agents.auditor as auditor_pkg

        pkg_dir = Path(auditor_pkg.__file__).parent
        hits: list[str] = []
        for py in pkg_dir.rglob("*.py"):
            if py.name == "checks.py":
                continue
            if "check_test_imports_exist" in py.read_text():
                hits.append(str(py))
        assert hits, (
            "check_test_imports_exist is defined but nothing in "
            "stronghold.agents.auditor/* references it — wire it into "
            "the dispatcher."
        )
