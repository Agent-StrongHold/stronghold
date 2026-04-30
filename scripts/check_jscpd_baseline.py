"""G-3 wrapper around jscpd with baseline-aware clone-pair filtering.

Spec: ARCHITECTURE.md §16.4.3.

Reads .jscpd-baseline.json, runs jscpd (or replays its JSON report),
exits per §16.7.2:
  0 — duplication_pct ≤ baseline ceiling AND every clone pair is permitted.
  1 — duplication_pct above ceiling OR a new (unbaselined) clone pair.
  2 — tool/baseline error (missing/malformed baseline, jscpd crash).

Stdlib + subprocess only. scripts/ stays src-isolated per §16.9.9.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ClonePair:
    """A single jscpd clone, keyed on the unordered pair of files.

    file_pair is a tuple of (lo, hi) where lo ≤ hi alphabetically — this
    lets us compare clone pairs without caring whether jscpd reported
    A↔B or B↔A in any given run.
    """

    file_pair: tuple[str, str]
    lines: int
    tokens: int

    @property
    def key(self) -> tuple[str, str]:
        """The dimension we baseline on. Token/line counts are
        informational — only the *pair of files* counts as identity."""
        return self.file_pair


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def parse_jscpd_report(report_text: str) -> tuple[float, list[ClonePair]]:
    """Parse a jscpd JSON report into (duplication_pct, clone_pairs).

    duplication_pct is the global lines-duplication percentage (jscpd's
    `statistics.total.percentage`). clone_pairs is one entry per
    `duplicates[i]`, normalized so (A↔B) and (B↔A) produce identical
    keys.

    A malformed report (missing keys, wrong types) raises ValueError;
    main() converts that into exit code 2.
    """
    data: Any = json.loads(report_text)
    if not isinstance(data, dict):
        raise ValueError("jscpd report must be a JSON object")
    total = data.get("statistics", {}).get("total", {})
    pct = float(total.get("percentage", 0.0))
    pairs: list[ClonePair] = []
    for d in data.get("duplicates", []):
        first = d.get("firstFile", {}).get("name")
        second = d.get("secondFile", {}).get("name")
        if not first or not second:
            continue
        pairs.append(
            ClonePair(
                file_pair=_normalize_pair(first, second),
                lines=int(d.get("lines", 0)),
                tokens=int(d.get("tokens", 0)),
            )
        )
    return pct, pairs


class BaselineError(Exception):
    """Raised when the baseline file is missing, unreadable, or malformed.

    main() converts this into exit code 2 — a tool/contract error, not
    a quality verdict (§16.7.2).
    """


def load_baseline(path: Path) -> dict[str, Any]:
    """Read and minimally validate .jscpd-baseline.json.

    Validation is shallow — `make baseline-jscpd` produces well-formed
    output; this guards against hand-edits that drop required keys.
    """
    if not path.exists():
        raise BaselineError(f"baseline file not found: {path}")
    try:
        data: Any = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BaselineError("baseline must be a JSON object at top level")
    if "max_duplication_pct" not in data:
        raise BaselineError("baseline must declare max_duplication_pct")
    if not isinstance(data.get("permitted_clone_pairs", []), list):
        raise BaselineError("permitted_clone_pairs must be a list")
    return data


def compare(
    pct: float, pairs: list[ClonePair], baseline: dict[str, Any]
) -> tuple[float | None, list[ClonePair]]:
    """Split jscpd output into (pct_overrun, net_new_pairs).

    pct_overrun is None when current ≤ baseline ceiling, otherwise the
    overrun amount (current − ceiling) for the failure message.

    net_new_pairs is the list of clone pairs whose file pair is not in
    baseline['permitted_clone_pairs']. The baseline's pairs are stored
    as 2-element lists; we normalise them the same way the parser does.
    """
    ceiling = float(baseline["max_duplication_pct"])
    pct_overrun = pct - ceiling if pct > ceiling else None

    permitted_keys: set[tuple[str, str]] = set()
    for entry in baseline.get("permitted_clone_pairs", []):
        if isinstance(entry, list | tuple) and len(entry) == 2:
            permitted_keys.add(_normalize_pair(entry[0], entry[1]))

    net_new = [p for p in pairs if p.key not in permitted_keys]
    return pct_overrun, net_new


def run_jscpd(path: str, min_tokens: int = 50, min_lines: int = 10) -> str:
    """Invoke jscpd, return its JSON-report contents.

    jscpd's `--reporters json` writes to a directory we control with
    --output. We use a temp dir so the caller never has to clean up.
    """
    with tempfile.TemporaryDirectory(prefix="jscpd-g3-") as tmp:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [
                "jscpd",
                "--min-tokens",
                str(min_tokens),
                "--min-lines",
                str(min_lines),
                "--reporters",
                "json",
                "--output",
                tmp,
                path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        # jscpd exits 0 when no clones above threshold and 1 when clones
        # exist or under various flag conditions. We don't use its exit
        # code — we read the report. Anything else (≥ 2) is a tool error.
        if proc.returncode not in (0, 1):
            raise subprocess.CalledProcessError(
                proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
            )
        report_path = Path(tmp) / "jscpd-report.json"
        if not report_path.exists():
            raise FileNotFoundError(f"jscpd did not produce a report at {report_path}")
        return report_path.read_text()


def _format_failure(pct: float, pct_overrun: float | None, net_new: list[ClonePair]) -> str:
    lines: list[str] = []
    if pct_overrun is not None:
        lines.append(
            f"FAIL: duplication is {pct:.2f}%, exceeds baseline ceiling "
            f"by {pct_overrun:.2f} percentage points."
        )
    if net_new:
        lines.append(f"FAIL: {len(net_new)} new clone pair(s) not in .jscpd-baseline.json:")
        for cp in net_new:
            a, b = cp.file_pair
            lines.append(f"  + {a}  ↔  {b}  ({cp.lines} lines, {cp.tokens} tokens)")
    lines.append(
        "Either remove the duplication, or — if intentional — regenerate "
        "the baseline via `make baseline-jscpd` and add a justification in the PR body."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint. Returns the exit code (0/1/2 per §16.7.2)."""
    parser = argparse.ArgumentParser(
        description=(
            "G-3: enforce that .jscpd-baseline.json's duplication ceiling "
            "and clone-pair set are not exceeded."
        )
    )
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument(
        "--input",
        type=Path,
        help=(
            "Read jscpd JSON report from FILE instead of running jscpd. "
            "Hermetic-test hook; CI never sets this."
        ),
    )
    parser.add_argument("path", help="Source path to scan (e.g. src/stronghold/)")
    args = parser.parse_args(argv)

    try:
        baseline = load_baseline(args.baseline)
    except BaselineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.input is not None:
        try:
            report_text = args.input.read_text()
        except OSError as exc:
            print(f"ERROR: --input file unreadable: {exc}", file=sys.stderr)
            return 2
    else:
        try:
            report_text = run_jscpd(args.path)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"ERROR: jscpd failed: {exc}", file=sys.stderr)
            return 2

    try:
        pct, pairs = parse_jscpd_report(report_text)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: jscpd report malformed: {exc}", file=sys.stderr)
        return 2

    pct_overrun, net_new = compare(pct, pairs, baseline)

    if pct_overrun is None and not net_new:
        print(f"OK: {pct:.2f}% duplication, {len(pairs)} clone(s), all permitted by baseline.")
        return 0

    print(_format_failure(pct, pct_overrun, net_new))
    return 1


if __name__ == "__main__":
    sys.exit(main())
