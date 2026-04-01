"""Prompt diff engine: compare versions side-by-side.

Uses difflib for unified diff output, structured as typed dataclasses
for the API and dashboard to consume.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DiffLine:
    """A single line in a unified diff."""

    op: str  # "add", "remove", "context", "header"
    content: str
    old_lineno: int | None = None
    new_lineno: int | None = None


@dataclass(frozen=True)
class PromptDiff:
    """Structured diff between two prompt versions."""

    old_version: int
    new_version: int
    old_content: str
    new_content: str
    additions: int
    deletions: int
    diff_lines: list[str] = field(default_factory=list)


def compute_diff(
    old_content: str,
    new_content: str,
    *,
    old_label: str = "previous",
    new_label: str = "current",
    context_lines: int = 3,
) -> list[DiffLine]:
    """Compute a unified diff between two prompt versions.

    Returns a list of DiffLine objects for the dashboard to render.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=old_label,
        tofile=new_label,
        n=context_lines,
    )

    result: list[DiffLine] = []
    old_lineno = 0
    new_lineno = 0

    for line in diff:
        stripped = line.rstrip("\n")

        if line.startswith("---") or line.startswith("+++"):
            result.append(DiffLine(op="header", content=stripped))
        elif line.startswith("@@"):
            result.append(DiffLine(op="header", content=stripped))
            # Parse hunk header to reset line numbers
            parts = stripped.split()
            if len(parts) >= 3:  # noqa: PLR2004
                try:
                    old_lineno = abs(int(parts[1].split(",")[0]))
                    new_lineno = int(parts[2].split(",")[0])
                except (ValueError, IndexError):
                    pass
        elif line.startswith("-"):
            result.append(DiffLine(op="remove", content=stripped[1:], old_lineno=old_lineno))
            old_lineno += 1
        elif line.startswith("+"):
            result.append(DiffLine(op="add", content=stripped[1:], new_lineno=new_lineno))
            new_lineno += 1
        else:
            result.append(
                DiffLine(
                    op="context",
                    content=stripped[1:] if stripped.startswith(" ") else stripped,
                    old_lineno=old_lineno,
                    new_lineno=new_lineno,
                )
            )
            old_lineno += 1
            new_lineno += 1

    return result


def diff_versions(old_content: str, new_content: str) -> PromptDiff:
    """Compute a structured diff between two prompt content strings.

    Returns a PromptDiff with addition/deletion counts and unified diff lines.
    Version numbers default to 0 (caller can override via the dataclass).
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    raw_diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="old",
            tofile="new",
        )
    )

    additions = 0
    deletions = 0
    for line in raw_diff:
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    diff_strings = [line.rstrip("\n") for line in raw_diff]

    return PromptDiff(
        old_version=0,
        new_version=0,
        old_content=old_content,
        new_content=new_content,
        additions=additions,
        deletions=deletions,
        diff_lines=diff_strings,
    )


def diff_summary(diff: PromptDiff) -> str:
    """Human-readable summary of a PromptDiff.

    Returns e.g. "Version 2->3: +5 lines, -2 lines"
    """
    return (
        f"Version {diff.old_version}\u2192{diff.new_version}: "
        f"+{diff.additions} lines, -{diff.deletions} lines"
    )


_WS_PATTERN = re.compile(r"\s+")


def has_semantic_change(old: str, new: str) -> bool:
    """True if content differs after normalizing whitespace.

    Collapses all runs of whitespace (spaces, tabs, newlines) to a single
    space, then strips leading/trailing whitespace before comparing.
    """
    normalized_old = _WS_PATTERN.sub(" ", old).strip()
    normalized_new = _WS_PATTERN.sub(" ", new).strip()
    return normalized_old != normalized_new
