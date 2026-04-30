"""CLI / exit-code tests for scripts/xenon_with_baseline.py.

Uses --input (hermetic xenon-output replay) so tests never depend on a
real xenon install or on a particular state of src/stronghold/.

Exit codes follow ARCHITECTURE.md §16.7.2:
  0 = pass (no net-new, no regression)
  1 = fail (net-new violation OR regression)
  2 = tool/baseline error (missing/malformed baseline)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "xenon_with_baseline.py"


def _baseline_file(tmp_path: Path, *entries: tuple[str, str, str]) -> Path:
    p = tmp_path / ".xenon-baseline.json"
    p.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-30T00:00:00Z",
                "command": "make baseline-xenon",
                "thresholds": {"absolute": "C", "modules": "C", "average": "C"},
                "permitted_above_threshold": [
                    {"file": f, "block": b, "rank": r} for f, b, r in entries
                ],
            }
        )
    )
    return p


def _input_file(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "xenon.out"
    p.write_text(content)
    return p


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


# ── exit 0: clean / all-permitted ──────────────────────────────────────────


def test_exit_0_when_xenon_output_is_empty(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path)
    inp = _input_file(tmp_path, "")
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_exit_0_when_violations_match_baseline_exactly(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, ("src/a.py", "foo", "D"))
    inp = _input_file(tmp_path, 'ERROR:xenon:block "src/a.py:1 foo" has a rank of D\n')
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 0, result.stderr


# ── exit 1: net-new / regression ───────────────────────────────────────────


def test_exit_1_when_unbaselined_violation_appears(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path)
    inp = _input_file(tmp_path, 'ERROR:xenon:block "src/new.py:1 bad" has a rank of D\n')
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 1
    assert "net-new" in result.stdout
    assert "src/new.py" in result.stdout


def test_exit_1_when_baselined_block_regresses(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, ("src/a.py", "foo", "D"))
    inp = _input_file(tmp_path, 'ERROR:xenon:block "src/a.py:1 foo" has a rank of E\n')
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 1
    assert "regression" in result.stdout


def test_exit_1_failure_message_mentions_remediation(tmp_path: Path) -> None:
    """The failure output must tell developers what to do — §16.9.10
    requires gate output be actionable."""
    baseline = _baseline_file(tmp_path)
    inp = _input_file(tmp_path, 'ERROR:xenon:block "src/x.py:1 y" has a rank of D\n')
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert "make baseline-xenon" in result.stdout


# ── exit 2: tool/baseline error ────────────────────────────────────────────


def test_exit_2_when_baseline_file_missing(tmp_path: Path) -> None:
    inp = _input_file(tmp_path, "")
    result = _run("--baseline", str(tmp_path / "nope.json"), "--input", str(inp), "src/")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_exit_2_when_baseline_is_malformed(tmp_path: Path) -> None:
    bad = tmp_path / ".xenon-baseline.json"
    bad.write_text("{not json")
    inp = _input_file(tmp_path, "")
    result = _run("--baseline", str(bad), "--input", str(inp), "src/")
    assert result.returncode == 2
    assert "JSON" in result.stderr


def test_exit_2_when_input_file_unreadable(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path)
    result = _run("--baseline", str(baseline), "--input", str(tmp_path / "no.out"), "src/")
    assert result.returncode == 2


# ── argparse contract ──────────────────────────────────────────────────────


def test_baseline_argument_is_required(tmp_path: Path) -> None:
    result = _run("src/")
    assert result.returncode == 2  # argparse uses 2 for usage errors
    assert "--baseline" in result.stderr


def test_help_message_mentions_g_1(tmp_path: Path) -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "G-1" in result.stdout


# ── cross-cutting: integration with parser + compare ───────────────────────


def test_real_world_snapshot_against_full_baseline_passes(tmp_path: Path) -> None:
    """If the baseline lists every current offender, the gate is green —
    this is the post-`make baseline-xenon` state every PR-author hits
    after first wiring G-1."""
    snapshot = (
        'ERROR:xenon:block "src/a.py:1 foo" has a rank of D\n'
        'ERROR:xenon:block "src/b.py:2 bar" has a rank of E\n'
        "ERROR:xenon:module 'src/c.py' has a rank of D\n"
    )
    baseline = _baseline_file(
        tmp_path,
        ("src/a.py", "foo", "D"),
        ("src/b.py", "bar", "E"),
        ("src/c.py", "module", "D"),
    )
    inp = _input_file(tmp_path, snapshot)
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 0, result.stdout + result.stderr


def test_partial_baseline_flags_only_unbaselined_offenders(tmp_path: Path) -> None:
    """The gate must report *only* the offenders the baseline doesn't
    cover — false-positives noise is what §16.9.10 calls out."""
    snapshot = (
        'ERROR:xenon:block "src/a.py:1 foo" has a rank of D\n'  # baselined
        'ERROR:xenon:block "src/b.py:2 bar" has a rank of E\n'  # NEW
    )
    baseline = _baseline_file(tmp_path, ("src/a.py", "foo", "D"))
    inp = _input_file(tmp_path, snapshot)
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 1
    assert "src/b.py" in result.stdout
    assert "src/a.py" not in result.stdout  # noise check
