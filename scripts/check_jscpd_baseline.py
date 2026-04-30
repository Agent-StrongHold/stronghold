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
