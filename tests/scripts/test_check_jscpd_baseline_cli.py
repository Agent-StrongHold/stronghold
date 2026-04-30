"""CLI tests for scripts/check_jscpd_baseline.py.

Uses --input (hermetic jscpd-report replay) so tests never depend on
a real jscpd install. The subprocess path is exercised by smoke-test
in CI, not here.

Exit codes per §16.7.2:
  0 = pass (pct ≤ ceiling AND every clone pair permitted)
  1 = fail (pct over ceiling OR new clone pair, or both)
  2 = tool/contract error (mutex flags, unreadable file, jscpd crash,
      malformed report)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_jscpd_baseline.py"


def _baseline_file(tmp_path: Path, ceiling: float, *pairs: tuple[str, str]) -> Path:
    p = tmp_path / ".jscpd-baseline.json"
    p.write_text(
        json.dumps(
            {
                "generated_at": "2026-04-30T00:00:00Z",
                "command": "make baseline-jscpd",
                "max_duplication_pct": ceiling,
                "permitted_clone_pairs": [list(pair) for pair in pairs],
            }
        )
    )
    return p


def _input_file(tmp_path: Path, pct: float, *clones: tuple[str, str, int, int]) -> Path:
    p = tmp_path / "report.json"
    p.write_text(
        json.dumps(
            {
                "statistics": {"total": {"percentage": pct}},
                "duplicates": [
                    {
                        "firstFile": {"name": a},
                        "secondFile": {"name": b},
                        "lines": lines,
                        "tokens": tokens,
                    }
                    for a, b, lines, tokens in clones
                ],
            }
        )
    )
    return p


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


# ── exit 0 ─────────────────────────────────────────────────────────────────


def test_exit_0_when_no_clones_and_pct_zero(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    inp = _input_file(tmp_path, 0.0)
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_exit_0_when_clones_match_baseline(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0, ("src/a.py", "src/b.py"))
    inp = _input_file(tmp_path, 2.0, ("src/a.py", "src/b.py", 12, 100))
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 0


def test_exit_0_when_pct_at_ceiling(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    inp = _input_file(tmp_path, 5.0)
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 0


# ── exit 1: clone-pair growth ──────────────────────────────────────────────


def test_exit_1_when_new_clone_pair_appears(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    inp = _input_file(tmp_path, 1.0, ("src/x.py", "src/y.py", 20, 150))
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 1
    assert "src/x.py" in result.stdout
    assert "src/y.py" in result.stdout
    assert "1 new clone" in result.stdout


def test_exit_1_when_pct_over_ceiling(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    inp = _input_file(tmp_path, 7.5)
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 1
    assert "7.50%" in result.stdout
    assert "ceiling" in result.stdout


def test_exit_1_reports_both_overrun_and_new_pair(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    inp = _input_file(tmp_path, 6.0, ("src/x.py", "src/y.py", 20, 150))
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert result.returncode == 1
    assert "ceiling" in result.stdout
    assert "1 new clone" in result.stdout


def test_exit_1_failure_message_mentions_remediation(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    inp = _input_file(tmp_path, 1.0, ("src/x.py", "src/y.py", 20, 150))
    result = _run("--baseline", str(baseline), "--input", str(inp), "src/")
    assert "make baseline-jscpd" in result.stdout
    assert "remove the duplication" in result.stdout


# ── exit 2: contract errors ────────────────────────────────────────────────


def test_exit_2_when_baseline_missing(tmp_path: Path) -> None:
    inp = _input_file(tmp_path, 0.0)
    result = _run("--baseline", str(tmp_path / "nope.json"), "--input", str(inp), "src/")
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_exit_2_when_baseline_malformed(tmp_path: Path) -> None:
    bad = tmp_path / ".jscpd-baseline.json"
    bad.write_text("{not json")
    inp = _input_file(tmp_path, 0.0)
    result = _run("--baseline", str(bad), "--input", str(inp), "src/")
    assert result.returncode == 2


def test_exit_2_when_baseline_lacks_required_ceiling(tmp_path: Path) -> None:
    bad = tmp_path / ".jscpd-baseline.json"
    bad.write_text(json.dumps({"permitted_clone_pairs": []}))
    inp = _input_file(tmp_path, 0.0)
    result = _run("--baseline", str(bad), "--input", str(inp), "src/")
    assert result.returncode == 2
    assert "max_duplication_pct" in result.stderr


def test_exit_2_when_input_unreadable(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    result = _run("--baseline", str(baseline), "--input", str(tmp_path / "no.json"), "src/")
    assert result.returncode == 2


def test_exit_2_when_input_is_not_jscpd_shaped(tmp_path: Path) -> None:
    baseline = _baseline_file(tmp_path, 5.0)
    bad = tmp_path / "report.json"
    bad.write_text("[1, 2, 3]")  # array not object
    result = _run("--baseline", str(baseline), "--input", str(bad), "src/")
    assert result.returncode == 2
    assert "malformed" in result.stderr


# ── argparse / metadata ────────────────────────────────────────────────────


def test_baseline_argument_required(tmp_path: Path) -> None:
    result = _run("src/")
    assert result.returncode == 2
    assert "--baseline" in result.stderr


def test_help_message_mentions_g_3(tmp_path: Path) -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "G-3" in result.stdout
