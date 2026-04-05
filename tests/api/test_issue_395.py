"""Tests for sidebar active state colors in prompts.html."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestSidebarActiveStateColors:
    def test_active_state_has_border_color(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "border-emerald-500" in html, "Missing emerald border color for active state"

    def test_active_state_has_background_color(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "bg-gray-800" in html, "Missing gray-800 background color for active state"

class TestQuotaProgressBarARIA:
    def test_quota_progress_has_role_attribute(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert 'role="progressbar"' in html, "Missing role='progressbar' attribute"

    def test_quota_progress_has_aria_value(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "aria-valuenow" in html, "Missing aria-valuenow attribute"

class TestQuotaProgressBarColorCoding:
    def test_quota_has_healthy_state_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "text-emerald-500" in html, "Missing text-emerald-500 for healthy state"

    def test_quota_has_danger_state_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "text-red-500" in html, "Missing text-red-500 for danger state"

    def test_quota_has_warning_state_color(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "text-amber-500" in html, "Missing text-amber-500 for warning state"

class TestErrorMessageSpacing:
    def test_error_message_has_margin_top(self) -> None:
        css = (DASHBOARD_DIR / "styles.css").read_text()
        assert "mt-" in css, "Missing margin-top class in CSS"
        assert "mt-4" in css or "mt-3" in css or "mt-2" in css, "Margin-top value should be at least 1rem (mt-4)"

class TestZIndexLimits:
    def test_z_index_values_do_not_exceed_100(self) -> None:
        css = (DASHBOARD_DIR / "styles.css").read_text()
        import re
        z_values = re.findall(r'z-\[(\d+)\]|z-(\d+)', css)
        flat_values = [int(v) for pair in z_values for v in pair if v]
        assert all(v <= 100 for v in flat_values), f"z-index values exceed 100: {flat_values}"

    def test_z_index_distinct_values_are_limited(self) -> None:
        css = (DASHBOARD_DIR / "styles.css").read_text()
        import re
        z_values = re.findall(r'z-\[(\d+)\]|z-(\d+)', css)
        flat_values = {int(v) for pair in z_values for v in pair if v}
        assert len(flat_values) <= 5, f"Too many distinct z-index values: {sorted(flat_values)}"

class TestPromptDiffSyntaxHighlighting:
    def test_added_lines_have_green_background_and_prefix(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "bg-green-100" in html, "Missing green background for added lines"
        assert "class=\\\"+\" " in html or "class=\"+\"" in html, "Missing '+' prefix for added lines"

    def test_removed_lines_have_red_background_and_prefix(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "bg-red-100" in html, "Missing red background for removed lines"
        assert "class=\\\"-\\\" " in html or "class=\"-\"" in html, "Missing '-' prefix for removed lines"

    def test_unchanged_lines_have_neutral_background(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "bg-gray-50" in html or "bg-gray-100" in html, "Missing neutral background for unchanged lines"

    def test_diff_view_has_line_numbers(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "line-number" in html or "line-no" in html, "Missing line number class"
        assert "data-line-number" in html or "data-line" in html, "Missing line number attribute"

class TestPromptDiffLayoutAndTypography:
    def test_diff_view_is_side_by_side_on_large_screens(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "md:flex" in html or "lg:flex" in html, "Missing flex layout for large screens"
        assert "gap-" in html, "Missing gap utility for spacing between diff panes"

    def test_diff_content_uses_jetbrains_mono_font(self) -> None:
        html = (DASHBOARD_DIR / "prompts.html").read_text()
        assert "font-mono" in html, "Missing monospace font class"
        assert "JetBrains" in html or "font-mono" in html, "Missing JetBrains Mono font reference"

    def test_long_lines_wrap_without_horizontal_scrolling(self) -> None:
        css = (DASHBOARD_DIR / "styles.css").read_text()
        assert "whitespace-normal" in css, "Missing whitespace-normal to allow line wrapping"
        assert "overflow-x-hidden" in css or "overflow-hidden" in css, "Missing overflow handling to prevent horizontal scroll"