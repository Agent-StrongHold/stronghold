"""CLI tests for scripts/check_vulture_whitelist.py.

Uses --from-file / --to-file (hermetic file replay) so tests never
need a live git repo. The --base path goes through subprocess to git
and is exercised by ./scripts/test.sh in CI, not here.

Exit codes per §16.7.2:
  0 = pass (no entries added; entries removed or unchanged)
  1 = fail (one or more entries added)
  2 = tool/contract error (mutex flags, unreadable file, git error)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_vulture_whitelist.py"


def _whitelist_file(tmp_path: Path, name: str, *entries: str) -> Path:
    """Write a synthetic whitelist file with the given entries."""
    p = tmp_path / name
    body = "# header prose\n\n" + "".join(
        f"{e}  # unused class (src/x.py:{i})\n" for i, e in enumerate(entries, start=1)
    )
    p.write_text(body)
    return p


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


# ── exit 0: shrink or no-op ────────────────────────────────────────────────


def test_exit_0_when_whitelist_unchanged(tmp_path: Path) -> None:
    base = _whitelist_file(tmp_path, "base", "Foo", "Bar")
    head = _whitelist_file(tmp_path, "head", "Foo", "Bar")
    result = _run("--from-file", str(base), "--to-file", str(head))
    assert result.returncode == 0, result.stderr
    assert "unchanged" in result.stdout


def test_exit_0_when_whitelist_shrinks(tmp_path: Path) -> None:
    base = _whitelist_file(tmp_path, "base", "Foo", "Bar", "Baz")
    head = _whitelist_file(tmp_path, "head", "Foo", "Bar")
    result = _run("--from-file", str(base), "--to-file", str(head))
    assert result.returncode == 0
    assert "shrank by 1" in result.stdout


def test_exit_0_when_head_whitelist_is_empty(tmp_path: Path) -> None:
    """Heroic-shrink: every offender refactored away. The §16.4.2
    'eventual state'."""
    base = _whitelist_file(tmp_path, "base", "OnlyOne")
    head = tmp_path / "head"
    head.write_text("# nothing left to whitelist\n")
    result = _run("--from-file", str(base), "--to-file", str(head))
    assert result.returncode == 0


# ── exit 1: growth ─────────────────────────────────────────────────────────


def test_exit_1_when_one_entry_added(tmp_path: Path) -> None:
    base = _whitelist_file(tmp_path, "base", "Foo")
    head = _whitelist_file(tmp_path, "head", "Foo", "NewEntry")
    result = _run("--from-file", str(base), "--to-file", str(head))
    assert result.returncode == 1
    assert "NewEntry" in result.stdout
    assert "grew by 1" in result.stdout


def test_exit_1_swap_is_still_fail(tmp_path: Path) -> None:
    """Net-zero entry swap: one removed, one added. Still blocks —
    the policy is shrink-only, not shrink-or-swap (§16.4.2)."""
    base = _whitelist_file(tmp_path, "base", "OldName")
    head = _whitelist_file(tmp_path, "head", "NewName")
    result = _run("--from-file", str(base), "--to-file", str(head))
    assert result.returncode == 1
    assert "NewName" in result.stdout
    assert "also removed 1" in result.stdout


def test_exit_1_failure_message_mentions_label_and_remediation(tmp_path: Path) -> None:
    """§16.9.10 actionable output — the developer must know the two
    paths forward (apply the label, or fix the dead code)."""
    base = _whitelist_file(tmp_path, "base")
    head = _whitelist_file(tmp_path, "head", "NewEntry")
    result = _run("--from-file", str(base), "--to-file", str(head))
    assert "vulture-whitelist-grow" in result.stdout
    assert "fix the dead code" in result.stdout


# ── exit 2: contract error ─────────────────────────────────────────────────


def test_exit_2_when_no_base_argument_given(tmp_path: Path) -> None:
    head = _whitelist_file(tmp_path, "head")
    result = _run("--to-file", str(head))
    assert result.returncode == 2
    assert "required" in result.stderr


def test_exit_2_when_both_base_args_given(tmp_path: Path) -> None:
    base = _whitelist_file(tmp_path, "base")
    result = _run("--base", "origin/integration", "--from-file", str(base))
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr


def test_exit_2_when_from_file_unreadable(tmp_path: Path) -> None:
    head = _whitelist_file(tmp_path, "head")
    result = _run("--from-file", str(tmp_path / "nope"), "--to-file", str(head))
    assert result.returncode == 2


def test_exit_2_when_to_file_unreadable(tmp_path: Path) -> None:
    base = _whitelist_file(tmp_path, "base")
    result = _run("--from-file", str(base), "--to-file", str(tmp_path / "nope"))
    assert result.returncode == 2


# ── help / metadata ────────────────────────────────────────────────────────


def test_help_message_mentions_g_2_and_label(tmp_path: Path) -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "G-2" in result.stdout
    assert "vulture-whitelist-grow" in result.stdout
