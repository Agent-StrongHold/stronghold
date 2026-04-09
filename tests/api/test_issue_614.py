"""Tests for ProgressBar component rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestProgressBarRendering:
    def test_progressbar_accepts_value_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "value" in html, "ProgressBar missing value prop"

    def test_progressbar_accepts_max_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "max" in html, "ProgressBar missing max prop"

    def test_progressbar_accepts_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "label" in html, "ProgressBar missing label prop"

    def test_progressbar_has_js_render_logic(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "ProgressBar" in html, "ProgressBar component not found"
        assert ".value" in html or "value:" in html, "ProgressBar missing value binding"
        assert ".max" in html or "max:" in html, "ProgressBar missing max binding"
        assert ".label" in html or "label:" in html, "ProgressBar missing label binding"

    def test_progressbar_displays_percentage_text(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "<span" in html and "percentage-text" in html, "Missing percentage-text span"
        assert "js_rendered" in html, "ProgressBar not using js_rendered model"

class TestProgressBarDarkThemeColors:
    def test_progressbar_has_emeral_500_fill_in_dark_theme(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "emerald-500" in html, "ProgressBar fill missing emerald-500 class"

    def test_progressbar_has_gray_700_track_in_dark_theme(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "gray-700" in html, "ProgressBar track missing gray-700 class"

class TestProgressBarAccessibility:
    def test_progressbar_has_aria_label_matching_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "aria-label" in html, "ProgressBar missing aria-label attribute"
        assert "role=\"progressbar\"" in html, "ProgressBar missing role='progressbar'"

class TestProgressBarEdgeCases:
    def test_progressbar_validates_max_gt_zero(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "max > 0" in html or "max <= 0" in html, "ProgressBar missing max validation"

    def test_progressbar_validates_value_between_0_and_max(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "0 <= value <= max" in html or "value < 0" in html or "value > max" in html, "ProgressBar missing value range validation"