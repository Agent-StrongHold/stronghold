"""Tests for sidebar active state styling."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestSidebarActiveState:
    def test_active_state_has_correct_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'class="sidebar-item active"' in html, "Missing active state class on sidebar item"
        assert "border-emerald-500" in html, "Missing emerald border color"
        assert "bg-gray-800" in html, "Missing gray-800 background"