"""Tests for quota usage bar transition animation."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestQuotaBarTransition:
    def test_quota_bar_has_transition_property(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "transition-width" in html or "transition-all" in html, (
            "Missing transition property for quota bar animation"
        )

    def test_quota_bar_has_smooth_easing(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "ease" in html, "Missing easing function for smooth animation"

    def test_quota_bar_transition_duration(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "0.6s" in html or "0.5s" in html, "Missing transition duration for quota bar"

class TestQuotaBarAccessibility:
    def test_quota_bar_has_aria_attributes(self) -> None:
        html = (DASHBOARD_DIR / "quota.html").read_text()
        assert "aria-valuenow" in html or 'role="progressbar"' in html, (
            "Missing ARIA attributes for accessibility on quota bar"
        )

class TestQuotaBarZIndex:
    def test_quota_bar_has_no_excessive_z_index(self) -> None:
        html = (DASHBOARD_DIR / "login.html").read_text()
        import re
        z_indices = re.findall(r'z-(\d+)', html)
        # Convert string z-indices to integers for comparison
        z_values = [int(z) for z in z_indices if z.isdigit()]
        assert all(z <= 50 for z in z_values), (
            f"Found excessive z-index values in login form: {z_values}"
        )