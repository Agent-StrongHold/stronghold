"""OnboardingContext: issue type detection + section-aware context injection.

Extracted from RuntimePipeline to enable isolated testing of onboarding
section matching and prompt prepending.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class IssueType:
    """Maps issue signals to onboarding sections. Extensible — just append."""

    name: str
    signals: list[str]       # path patterns, title prefixes, keywords
    sections: list[str]      # ONBOARDING.md section headers to inject
    priority: int = 0        # higher = matched first (most specific wins)


# Re-export the registry from the pipeline __init__ (it's defined there
# alongside the RuntimePipeline class). This module provides the
# IssueType class and the detection/parsing logic.

# Import ISSUE_TYPE_REGISTRY lazily to avoid circular imports
def _get_registry() -> list[IssueType]:
    from stronghold.builders.pipeline import ISSUE_TYPE_REGISTRY
    return ISSUE_TYPE_REGISTRY


class OnboardingContext:
    """Issue type detection + section-aware context injection."""

    @staticmethod
    def detect_issue_type(run: Any) -> IssueType:
        """Match issue signals against registry. Highest priority match wins."""
        registry = _get_registry()
        title = getattr(run, "_issue_title", "").lower()
        content = getattr(run, "_issue_content", "").lower()
        affected = getattr(run, "_analysis", {}).get("affected_files", [])
        search_text = f"{title} {content} {' '.join(affected)}"

        for itype in sorted(registry, key=lambda t: -t.priority):
            if not itype.signals:
                continue
            if any(signal in search_text for signal in itype.signals):
                return itype

        return min(registry, key=lambda t: t.priority)

    @staticmethod
    def parse_sections(text: str) -> dict[str, str]:
        """Split ONBOARDING.md into sections by ## and ### headers."""
        sections: dict[str, str] = {}
        current_name = ""
        current_lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("## ") or line.startswith("### "):
                if current_name:
                    sections[current_name] = "\n".join(current_lines)
                current_name = line.lstrip("#").strip()
                current_lines = [line]
            else:
                current_lines.append(line)
        if current_name:
            sections[current_name] = "\n".join(current_lines)
        return sections
