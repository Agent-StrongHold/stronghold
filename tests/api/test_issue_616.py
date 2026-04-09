"""Tests for dashboard component props and rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestDashboardComponentProps:
    def test_component_accepts_icon_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "icon" in html, "Component missing icon prop definition"

    def test_component_accepts_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "label" in html, "Component missing label prop definition"

    def test_component_accepts_count_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "count" in html, "Component missing count prop definition"

class TestDashboardComponentRendering:
    def test_jsx_renders_icon_value(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert ".icon" in html or "icon:" in html, "JSX missing icon rendering"

    def test_jsx_renders_label_value(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert ".label" in html or "label:" in html, "JSX missing label rendering"

    def test_jsx_renders_count_value(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert ".count" in html or "count:" in html, "JSX missing count rendering"

class TestDashboardGridLayout:
    def test_grid_layout_has_tailwind_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "grid" in html, "Missing grid container class"
        assert "grid-cols-" in html, "Missing grid columns classes"

    def test_grid_layout_has_responsive_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "md:grid-cols-" in html or "sm:grid-cols-" in html or "lg:grid-cols-" in html, "Missing responsive grid classes"

    def test_grid_items_have_layout_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "gap-" in html or "gap-x-" in html or "gap-y-" in html, "Missing gap classes for grid spacing"

class TestDashboardComponentReusability:
    def test_component_has_type_definitions(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "interface" in html or "type" in html, "Missing TypeScript interface or type definition"

    def test_component_not_hardcoded_values(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "icon={" not in html, "Component has hardcoded icon value"
        assert "label={" not in html, "Component has hardcoded label value"
        assert "count={" not in html, "Component has hardcoded count value"

class TestDashboardAccessibilityAttributes:
    def test_component_has_aria_labels(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "aria-label=" in html, "Component missing aria-label attributes"
        assert "aria-labelledby=" in html, "Component missing aria-labelledby attributes"

    def test_component_has_appropriate_roles(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "role=" in html, "Component missing role attributes"
        assert "button" in html or "region" in html or "alert" in html, "Component missing common role values"

class TestDashboardComponentPropValidation:
    def test_component_has_prop_types_validation(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "PropTypes" in html, "Component missing PropTypes validation"

    def test_component_prop_types_are_required(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "isRequired" in html, "Component missing required prop validation"

    def test_component_handles_missing_props_gracefully(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "defaultProps" in html or "fallback" in html or "||" in html, "Component may not handle missing props gracefully"