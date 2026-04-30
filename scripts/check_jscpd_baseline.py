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

import json
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
