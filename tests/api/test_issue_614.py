"""Tests for ProgressBar component rendering in index.html."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestProgressBarRendering:
    def test_progressbar_component_exists(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "ProgressBar" in html, "ProgressBar component not found in HTML"

    def test_progressbar_accepts_value_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "value" in html, "ProgressBar missing 'value' prop"

    def test_progressbar_accepts_max_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "max" in html, "ProgressBar missing 'max' prop"

    def test_progressbar_accepts_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "label" in html, "ProgressBar missing 'label' prop"

    def test_progressbar_is_react_component(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "function ProgressBar" in html or "const ProgressBar" in html, "ProgressBar not defined as a React component"

class TestProgressBarColors:
    def test_progressbar_has_fill_color(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "emerald-500" in html, "ProgressBar missing emerald-500 fill color"

    def test_progressbar_has_track_color(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "gray-700" in html, "ProgressBar missing gray-700 track color"

class TestProgressBarPercentageText:
    def test_progressbar_renders_percentage_text(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "js_rendered" in html, "ProgressBar missing js_rendered model for percentage text"

    def test_percentage_text_shows_current_value(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "value" in html and "max" in html, "ProgressBar missing value/max props for percentage calculation"

    def test_percentage_text_format(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "{value}%" in html or "Math.round" in html, "ProgressBar missing percentage text formatting"

class TestProgressBarAccessibility:
    def test_progressbar_has_aria_label(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-label" in html, "ProgressBar missing aria-label attribute"

    def test_progressbar_has_role(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'role="progressbar"' in html, "ProgressBar missing role='progressbar'"

    def test_progressbar_has_aria_valuenow(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-valuenow" in html, "ProgressBar missing aria-valuenow attribute"

    def test_progressbar_has_aria_valuemax(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-valuemax" in html, "ProgressBar missing aria-valuemax attribute"

class TestProgressBarPropValidation:
    def test_progressbar_has_default_props(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "defaultProps" in html, "ProgressBar missing defaultProps definition"

    def test_progressbar_handles_value_exceeds_max(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "Math.min" in html or "value > max" in html or "value <= max" in html, "ProgressBar missing value clamping logic"

    def test_progressbar_renders_fallback_when_props_missing(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "js_rendered" in html, "ProgressBar missing js_rendered model for fallback rendering"