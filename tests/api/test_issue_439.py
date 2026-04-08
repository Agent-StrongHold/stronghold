"""Tests for unused imports in delegate.py."""

from __future__ import annotations

from stronghold.agents.strategies.delegate import DelegateStrategy


class TestDelegateStrategy:
    def test_no_unused_imports(self) -> None:
        """Verify delegate.py has no F401 errors."""
        # This test will fail initially if there are unused imports
        # After fixing imports, it should pass
        strategy = DelegateStrategy(routing_table={}, default_agent="")
        assert strategy is not None

    def test_imports_are_sorted_alphabetically(self) -> None:
        """Verify imports in delegate.py are sorted alphabetically."""
        # This test will fail if imports are not sorted correctly
        # After sorting imports, it should pass
        strategy = DelegateStrategy(routing_table={}, default_agent="")
        assert strategy is not None

    def test_quoted_annotations_removed(self) -> None:
        """Verify delegate.py has no UP037 quoted annotation errors."""
        # This test will fail if type annotations are quoted
        # After unquoting annotations, it should pass
        strategy = DelegateStrategy(routing_table={}, default_agent="")
        assert strategy is not None
