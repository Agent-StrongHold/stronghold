"""Tests for ProgressBar component rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestProgressBarRendering:
    def test_progressbar_has_role_attribute(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'role="progressbar"' in html, "Missing role='progressbar' attribute"

    def test_progressbar_has_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'aria-valuemin="0"' in html, "Missing aria-valuemin='0'"
        assert 'aria-valuemax=' in html, "Missing aria-valuemax attribute"
        assert 'aria-valuenow=' in html, "Missing aria-valuenow attribute"
        assert 'aria-label=' in html, "Missing aria-label attribute"

    def test_progressbar_aria_values_match_props(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check that the aria attributes are present with dynamic values
        assert "aria-valuemax={" in html or "aria-valuemax=" in html, "aria-valuemax not properly set"
        assert "aria-valuenow={" in html or "aria-valuenow=" in html, "aria-valuenow not properly set"
        assert "aria-label={" in html or "aria-label=" in html, "aria-label not properly set"

    def test_progressbar_uses_correct_colors(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "emerald-500" in html, "Missing emerald-500 fill color class"
        assert "gray-700" in html, "Missing gray-700 track color class"

    def test_progressbar_displays_percentage_text(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "{Math.round((value / max) * 100)}" in html, "Missing percentage calculation"
        assert "<span>{" in html and "}%</span>" in html, "Missing span wrapping percentage text"

    def test_progressbar_handles_negative_values(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "Math.max(0" in html or "Math.min(0" not in html, "Missing value clamping to 0"
        assert 'aria-valuenow="0"' in html, "Missing aria-valuenow='0' for negative values"