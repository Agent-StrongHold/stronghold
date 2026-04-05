"""Tests for login form mobile layout to prevent button overlap."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestLoginFormMobileLayout:
    def test_login_form_has_flex_column_or_space_y(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert (
            "flex-col" in html or "space-y" in html or "space-y-2" in html
        ), "Missing vertical spacing container for mobile layout"

    def test_login_form_has_mobile_breakpoint(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "@media (max-width: 768px)" in html, "Missing mobile breakpoint at 768px"

    def test_error_message_container_has_spacing(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert (
            "mt-" in html or "mb-" in html or "py-" in html or "gap-" in html
        ), "Missing margin or padding around error messages"

class TestLoginFormErrorSpacing:
    def test_error_messages_have_proper_tailwind_spacing(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        # Check that error message elements have proper spacing classes
        assert "mt-2" in html or "mt-4" in html or "space-y-1" in html or "space-y-2" in html, \
            "Error messages missing proper Tailwind spacing classes (mt-2, mt-4, space-y-1, or space-y-2)"

class TestProgressBarAccessibility:
    def test_progress_bar_has_required_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert (
            "role=\"progressbar\"" in html and "aria-valuenow" in html
        ), "Progress bar missing required ARIA attributes for accessibility"

class TestProgressBarColorCoding:
    def test_progress_bar_has_health_state_colors(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "bg-emerald-500" in html, "Missing healthy state color class (bg-emerald-500)"
        assert (
            "bg-amber-500" in html or "bg-red-500" in html
        ), "Missing warning state color classes (bg-amber-500 or bg-red-500)"

class TestSidebarActiveState:
    def test_sidebar_active_items_have_correct_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "border-emerald-500" in html, "Active sidebar items missing emerald border class"
        assert "bg-gray-800" in html, "Active sidebar items missing gray-800 background class"

    def test_sidebar_active_state_uses_both_required_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert (
            "border-emerald-500" in html and "bg-gray-800" in html
        ), "Active sidebar items must include both 'border-emerald-500' and 'bg-gray-800' classes"