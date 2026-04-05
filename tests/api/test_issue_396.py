"""Tests for sidebar active state styling."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestSidebarActiveStateStyling:
    def test_sidebar_active_state_has_correct_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'class="sidebar-item active"' in html, "Missing active state class on sidebar item"
        assert "border-emerald-500" in html, "Missing emerald border color for active state"
        assert "bg-gray-800" in html, "Missing gray-800 background for active state"

    def test_root_element_has_smooth_scroll(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "scroll-smooth" in html, "Missing scroll-smooth class on root element"

class TestScrollBehavior:
    def test_root_element_has_smooth_scroll(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "scroll-smooth" in html, "Missing scroll-smooth class for smooth scrolling"

class TestProgressBarARIA:
    def test_progress_bar_has_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert 'role="progressbar"' in html, "Missing role='progressbar' attribute"
        assert "aria-valuenow" in html, "Missing aria-valuenow attribute"

    def test_progress_bar_has_aria_label(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "aria-label" in html, "Missing aria-label attribute"
        assert "aria-labelledby" in html, "Missing aria-labelledby attribute"

class TestErrorMessageSpacing:
    def test_error_message_has_spacing_classes(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        assert "mb-" in html or "my-" in html or "gap-" in html or "space-" in html, "Error message missing proper spacing classes (mb-, my-, gap-, or space-)"

class TestZIndexLimits:
    def test_z_index_values_are_limited(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        import re
        z_index_matches = re.findall(r'z-index:\s*(\d+)', html)
        for z_value in z_index_matches:
            assert int(z_value) <= 100, f"z-index value {z_value} exceeds maximum allowed value of 100"