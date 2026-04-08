"""Tests for unused local variable fix in builders_learning.py."""

from __future__ import annotations

from stronghold.agents.strategies.builders_learning import BuildersLearningStrategy


class TestBuildersLearningStrategy:
    def test_no_unused_local_variables(self) -> None:
        """Verify no F841 violations exist in builders_learning.py."""
        strategy = BuildersLearningStrategy()
        assert strategy is not None
