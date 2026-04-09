"""Tests for base template scroll-smooth class."""

from __future__ import annotations

from pathlib import Path

import pytest

DASHBOARD_DIR = Path("src/stronghold/dashboard")

class TestBaseTemplateScrollSmooth:
    def test_html_element_has_scroll_smooth_class(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        assert 'class="scroll-smooth"' in html, "HTML element missing scroll-smooth class"

    def test_scroll_smooth_class_not_duplicated(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Count occurrences of scroll-smooth class - should only appear once (on html element)
        count = html.count('scroll-smooth')
        assert count == 1, f"scroll-smooth class duplicated {count} times"

class TestNoConflictingScrollBehavior:
    def test_no_scroll_behavior_override_classes(self) -> None:
        html = (DASHBOARD_DIR / "index.html").read_text()
        # Check that html element doesn't have classes that override scroll behavior
        assert 'overflow-auto' not in html, "HTML element has conflicting overflow-auto class"
        assert 'overflow-hidden' not in html, "HTML element has conflicting overflow-hidden class"
        assert 'overflow-scroll' not in html, "HTML element has conflicting overflow-scroll class"
        assert 'overflow-x-auto' not in html, "HTML element has conflicting overflow-x-auto class"
        assert 'overflow-y-auto' not in html, "HTML element has conflicting overflow-y-auto class"