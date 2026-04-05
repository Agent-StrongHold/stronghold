"""Tests for sidebar active state indicator in quota.html."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestQuotaSidebarActiveState:
    def test_sidebar_active_state_classes(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "border-emerald-500" in html, "Missing active border color emerald-500"
        assert "bg-gray-800" in html, "Missing active background gray-800"

class TestQuotaProgressBarARIA:
    def test_quota_progress_bar_has_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "role=\"progressbar\"" in html, "Missing role='progressbar' attribute"
        assert "aria-valuenow" in html, "Missing aria-valuenow attribute for progress value"

    def test_quota_progress_bar_aria_value_min_max(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "aria-valuemin" in html, "Missing aria-valuemin attribute"
        assert "aria-valuemax" in html, "Missing aria-valuemax attribute"

class TestQuotaProgressBarColorCoding:
    def test_quota_healthy_has_emerald_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "bg-emerald-500" in html, "Missing emerald-500 color for healthy quota"

    def test_quota_warning_has_amber_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "bg-amber-500" in html, "Missing amber-500 color for warning quota"

    def test_quota_critical_has_red_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "bg-red-500" in html, "Missing red-500 color for critical quota"

class TestErrorMessageSpacing:
    def test_error_messages_have_proper_spacing(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        # Error messages should have proper spacing classes when following other elements
        assert "mt-4" in html or "space-y-2" in html or "flex-col" in html, \
            "Error messages missing proper spacing classes (mt-4, space-y-2, or flex-col)"

class TestErrorMessageSpacingInLogin:
    def test_login_error_messages_have_proper_spacing(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        # Error messages should have proper spacing classes when following other elements
        assert "mt-4" in html or "space-y-2" in html or "flex-col" in html, \
            "Error messages missing proper spacing classes (mt-4, space-y-2, or flex-col)"

class TestQuotaProgressBarTransition:
    def test_quota_progress_bar_has_transition_property(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        # Check for transition properties that would animate width changes
        assert "transition-width" in html or "transition-all" in html or "transition" in html, \
            "Progress bar missing transition property for smooth width changes"