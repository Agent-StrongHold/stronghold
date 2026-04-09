"""Tests for XPSourceCard component existence and props."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestXPSourceCardComponent:
    def test_component_exists(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "XPSourceCard" in html, "XPSourceCard component not found in HTML"

    def test_component_has_icon_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "icon" in html, "XPSourceCard missing icon prop definition"

    def test_component_has_label_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "label" in html, "XPSourceCard missing label prop definition"

    def test_component_has_count_prop(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert "count" in html, "XPSourceCard missing count prop definition"

    def test_xpsourcecard_structure_and_classes(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert 'class="bg-white rounded-lg shadow-md p-4"' in jsx, "Missing main div with correct classes"
        assert 'class="text-2xl mb-2"' in jsx, "Missing icon element with correct classes"
        assert 'class="text-sm font-medium text-gray-500"' in jsx, "Missing label element with correct classes"
        assert 'class="text-lg font-bold text-gray-900"' in jsx, "Missing count element with correct classes"

    def test_xpsourcecard_supports_grid_layout(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4" in jsx, "Missing grid container classes"
        assert "<XPSourceCard" in jsx, "Missing XPSourceCard instances in the component"

    def test_xpsourcecard_has_accessibility_attributes(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert 'aria-label=' in jsx, "Missing aria-label attribute on card element"
        assert 'role="region"' in jsx, "Missing role='region' attribute on card element"
        assert 'aria-live="polite"' in jsx, "Missing aria-live='polite' attribute on count element"

    def test_xpsourcecard_handles_missing_props_gracefully(self) -> None:
        jsx = (DASHBOARD_DIR / "XPSourceCard.jsx").read_text()
        assert "defaultProps" in jsx, "Missing defaultProps definition"
        assert "icon: " in jsx, "Missing default icon prop"
        assert "label: " in jsx, "Missing default label prop"
        assert "count: " in jsx, "Missing default count prop"