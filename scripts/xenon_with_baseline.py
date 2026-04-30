"""G-1 wrapper around xenon with baseline-aware violation filtering.

Spec: ARCHITECTURE.md §16.4.1.

Reads .xenon-baseline.json, runs xenon, exits:
  0 — only baseline-permitted violations (or none)
  1 — net-new offenders OR rank regression vs. baseline
  2 — tool/baseline error (missing/malformed baseline, xenon crash)

Stdlib + subprocess only — never imports from src/stronghold (§16.9.9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
