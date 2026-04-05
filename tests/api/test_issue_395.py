"""Tests for sidebar active state indicator in prompts.html."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestSidebarActiveState:
    def test_prompts_sidebar_has_active_classes(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "class=\"border-emerald-500 bg-gray-800\"" in html, (
            "Missing active state Tailwind classes in sidebar"
        )

    def test_sidebar_active_state_in_js(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "borderLeftColor = \"var(--emerald)\"" in html, (
            "Missing JS code to set active border color"
        )
        assert "classList.add('active')" in html, (
            "Missing JS code to add active class"
        )

    def test_sidebar_item_structure(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "sidebar-item" in html, "Missing sidebar-item class for navigation items"

class TestVersionDiffSyntaxHighlighting:
    def test_version_diff_has_syntax_highlighting(self) -> None:
        html = (DASHBOARD_DIR / "version_diff.html").read_text()
        assert "class=\"language-" in html or "class=\"syntax-highlight" in html, (
            "Missing syntax highlighting classes in version diff view"
        )

class TestQuotaProgressBarARIA:
    def test_quota_progress_bar_has_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert 'role="progressbar"' in html, "Missing role='progressbar' attribute"
        assert "aria-valuenow" in html, "Missing aria-valuenow attribute"

class TestErrorMessageSpacing:
    def test_error_messages_have_proper_spacing_classes(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "mt-" in html or "space-y-" in html or "flex-col" in html, (
            "Error messages missing proper spacing classes (mt-, space-y-, or flex-col)"
        )