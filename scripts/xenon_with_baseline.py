"""G-1 wrapper around xenon with baseline-aware violation filtering.

Spec: ARCHITECTURE.md §16.4.1.

Reads .xenon-baseline.json, runs xenon, exits:
  0 — only baseline-permitted violations (or none)
  1 — net-new offenders OR rank regression vs. baseline
  2 — tool/baseline error (missing/malformed baseline, xenon crash)

Stdlib + subprocess only — never imports from src/stronghold (§16.9.9).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RANK_ORDER = ("A", "B", "C", "D", "E", "F")
RANK_INDEX = {r: i for i, r in enumerate(RANK_ORDER)}

_BLOCK_RE = re.compile(
    r'^ERROR:xenon:block "(?P<file>[^"]+):\d+ (?P<block>[^"]+)" '
    r"has a rank of (?P<rank>[A-F])\s*$"
)
_MODULE_RE = re.compile(
    r"^ERROR:xenon:module '(?P<file>[^']+)' has a rank of (?P<rank>[A-F])\s*$"
)


@dataclass(frozen=True)
class Violation:
    file: str
    block: str  # function/class name, or literal "module" for module-level rank
    rank: str

    def is_worse_than(self, other_rank: str) -> bool:
        return RANK_INDEX[self.rank] > RANK_INDEX[other_rank]


def parse_xenon_output(text: str) -> list[Violation]:
    """Parse xenon's stderr/stdout into Violation records.

    Lines that don't match either the block or module ERROR shape are ignored
    so future xenon log additions (warnings, summaries) don't trip the parser.
    """
    out: list[Violation] = []
    for line in text.splitlines():
        m = _BLOCK_RE.match(line)
        if m:
            out.append(Violation(file=m["file"], block=m["block"], rank=m["rank"]))
            continue
        m = _MODULE_RE.match(line)
        if m:
            out.append(Violation(file=m["file"], block="module", rank=m["rank"]))
    return out


class BaselineError(Exception):
    """Raised when the baseline file is missing, unreadable, or malformed.

    main() converts this into exit code 2 — a tool/contract error, not a
    quality verdict (§16.7.2).
    """


def load_baseline(path: Path) -> dict[str, Any]:
    """Read and minimally validate the baseline JSON.

    Validation is intentionally shallow — we trust `make baseline-xenon`
    to produce well-shaped output. The check exists to give a clear
    error when someone hand-edits the file and breaks it.
    """
    if not path.exists():
        raise BaselineError(f"baseline file not found: {path}")
    try:
        data: Any = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BaselineError("baseline must be a JSON object at top level")
    permitted = data.get("permitted_above_threshold", [])
    if not isinstance(permitted, list):
        raise BaselineError("permitted_above_threshold must be a list")
    for entry in permitted:
        if not isinstance(entry, dict) or {"file", "block", "rank"} - entry.keys():
            raise BaselineError(
                "each permitted entry must have file/block/rank keys"
            )
    return data


def compare(
    violations: list[Violation], baseline: dict[str, Any]
) -> tuple[list[Violation], list[Violation]]:
    """Split violations into (net_new, regressions).

    A violation is *permitted* iff its (file, block) appears in the
    baseline AND its rank is ≤ the baselined rank. A worse rank on a
    baselined entry is a regression (e.g., D→E on a permitted block).
    """
    permitted: dict[tuple[str, str], str] = {
        (entry["file"], entry["block"]): entry["rank"]
        for entry in baseline.get("permitted_above_threshold", [])
    }
    net_new: list[Violation] = []
    regressions: list[Violation] = []
    for v in violations:
        baselined_rank = permitted.get((v.file, v.block))
        if baselined_rank is None:
            net_new.append(v)
        elif v.is_worse_than(baselined_rank):
            regressions.append(v)
    return net_new, regressions
