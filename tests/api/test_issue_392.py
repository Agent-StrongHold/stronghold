"""Tests for agent card description truncation indicator."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestAgentCardDescriptionTruncation:
    def test_agent_card_description_has_truncate_class(self) -> None:
        html = (DASHBOARD_DIR / "agents.html").read_text()
        assert "truncate" in html, "Agent card description missing 'truncate' class"

    def test_agent_card_description_has_text_overflow_ellipsis(self) -> None:
        html = (DASHBOARD_DIR / "agents.html").read_text()
        assert (
            "text-overflow: ellipsis" in html or "overflow-ellipsis" in html
        ), "Agent card description missing text-overflow: ellipsis"

    def test_agent_card_description_has_overflow_hidden(self) -> None:
        html = (DASHBOARD_DIR / "agents.html").read_text()
        assert (
            "overflow-hidden" in html
        ), "Agent card description missing overflow-hidden class"

    def test_agent_card_description_has_accessibility_attributes(self) -> None:
        html = (DASHBOARD_DIR / "agents.html").read_text()
        assert (
            "aria-label=" in html or "title=" in html
        ), "Agent card description missing accessibility attributes for truncated text"

    def test_agent_card_description_accessibility_matches_full_text(self) -> None:
        html = (DASHBOARD_DIR / "agents.html").read_text()
        # Check that aria-label or title attributes contain descriptive text
        import re
        aria_labels = re.findall(r'aria-label="([^"]*)"', html)
        titles = re.findall(r'title="([^"]*)"', html)
        assert any(len(label) > 10 for label in aria_labels), "aria-label too short for truncated description"
        assert any(len(title) > 10 for title in titles), "title attribute too short for truncated description"

    def test_agent_card_description_no_tooltip_for_truncated(self) -> None:
        html = (DASHBOARD_DIR / "agents.html").read_text()
        # Check that truncated descriptions don't have tooltip implementations
        assert "data-tooltip" not in html, "Truncated description has tooltip implementation"
        assert 'title=""' not in html, "Truncated description has empty title attribute"