"""Tests for sidebar active state styling in quota.html."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestQuotaSidebarActiveState:
    def test_sidebar_item_has_active_border_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "border-emerald-500" in html, "Active sidebar item missing emerald border"

    def test_sidebar_item_has_active_background(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "bg-gray-800" in html, "Active sidebar item missing gray-800 background"

class TestProfileProgressBarAccessibility:
    def test_progress_bar_has_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "profile.html").read_text()
        assert 'role="progressbar"' in html, "Progress bar missing role attribute"
        assert "aria-valuenow" in html, "Progress bar missing aria-valuenow attribute"

class TestProfileProgressBarAnimation:
    def test_progress_bar_has_transition_for_width(self) -> None:
        html = (DASHBOARD_DIR / "profile.html").read_text()
        assert "transition" in html, "Progress bar missing transition property"
        assert "width" in html, "Progress bar missing width in transition properties"

class TestProfileProgressBarCSSTransitions:
    def test_progress_bar_has_css_transition_for_smooth_animation(self) -> None:
        css = (DASHBOARD_DIR / "profile.css").read_text()
        assert "transition" in css, "Progress bar missing CSS transition property"
        assert "width" in css, "Progress bar missing width in CSS transition properties"

class TestLoginErrorSpacing:
    def test_error_message_has_proper_spacing(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        # Error messages should have margin or flex layout classes
        assert "mt-" in html or "mb-" in html or "py-" in html or "space-y" in html, "Error messages missing proper spacing classes"

    def test_error_message_no_negative_positioning(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        # Error messages should not use negative positioning
        assert "-mt-" not in html and "-mb-" not in html, "Error messages using negative positioning"
        assert "top-" not in html and "bottom-" not in html, "Error messages using top/bottom positioning"

class TestLoginZIndexControl:
    def test_no_z_index_exceeds_reasonable_limit(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        import re
        z_indices = re.findall(r'z-(\d+)', html)
        z_values = [int(z) for z in z_indices]
        assert all(z <= 100 for z in z_values), f"z-index values exceed limit: {z_values}"

    def test_no_unnecessary_z_index_usage(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        import re
        z_indices = re.findall(r'z-(\d+)', html)
        assert len(z_indices) <= 3, f"Too many z-index usages: {z_indices}"