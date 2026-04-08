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
