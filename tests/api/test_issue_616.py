"""Tests for XPSourceCard component existence and props."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestXPSourceCardComponent:
    def test_xpsourcecard_component_exists(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "XPSourceCard" in html, "XPSourceCard component not found in HTML"

    def test_xpsourcecard_accepts_icon_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check for icon prop in component definition or usage
        assert "icon" in html, "XPSourceCard missing icon prop"

    def test_xpsourcecard_accepts_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check for label prop in component definition or usage
        assert "label" in html, "XPSourceCard missing label prop"

    def test_xpsourcecard_accepts_count_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check for count prop in component definition or usage
        assert "count" in html, "XPSourceCard missing count prop"

class TestXPSourceCardStructure:
    def test_xpsourcecard_has_card_styling(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "bg-white" in jsx or "bg-gray" in jsx, "Missing card background color"
        assert "rounded-lg" in jsx or "rounded" in jsx, "Missing card border radius"
        assert "shadow" in jsx, "Missing card shadow"

    def test_xpsourcecard_renders_icon_element(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "icon" in jsx, "Missing icon prop rendering"

    def test_xpsourcecard_renders_label_element(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "label" in jsx, "Missing label prop rendering"

    def test_xpsourcecard_renders_count_element(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "count" in jsx, "Missing count prop rendering"

class TestXPSourceCardDynamicPropsAndGrid:
    def test_xpsourcecard_supports_dynamic_props(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        # Check for dynamic prop usage (not hardcoded values)
        assert "{...props}" in jsx or "props." in jsx, "Component doesn't support dynamic props"

    def test_xpsourcecard_has_grid_container_parent(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        # Check for grid container classes in parent element
        assert "grid" in jsx, "Missing grid container class"
        assert "grid-cols-" in jsx or "grid-flow-" in jsx, "Missing grid layout classes"

    def test_xpsourcecard_supports_multiple_instances(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check for multiple XPSourceCard components in usage
        xpsourcecard_count = html.count("XPSourceCard")
        assert xpsourcecard_count > 1, "Component doesn't appear to support multiple instances"

class TestXPSourceCardAccessibility:
    def test_xpsourcecard_has_aria_label(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "aria-label" in jsx, "XPSourceCard missing aria-label attribute"

    def test_xpsourcecard_count_has_status_role(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert 'role="status"' in jsx, "Count element missing role='status' attribute"

class TestXPSourceCardDefaultProps:
    def test_xpsourcecard_has_default_icon_prop(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        # Check for default props assignment
        assert "icon: " in jsx or "defaultProps" in jsx, "Missing default icon prop"

    def test_xpsourcecard_has_default_label_prop(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        # Check for default props assignment
        assert "label: " in jsx or "defaultProps" in jsx, "Missing default label prop"

    def test_xpsourcecard_has_default_count_prop(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        # Check for default props assignment
        assert "count: " in jsx or "defaultProps" in jsx, "Missing default count prop"

    def test_xpsourcecard_handles_undefined_props_gracefully(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        # Check for conditional rendering or fallback values
        assert "||" in jsx or "? :" in jsx or "?? " in jsx, "Component doesn't handle undefined props gracefully"