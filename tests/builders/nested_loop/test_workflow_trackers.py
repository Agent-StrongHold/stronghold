"""Tests for nested-loop workflow engine: outer loop, inner loop, test tracking.

Evidence-based contracts:
- MasonTestTracker implements high water mark and counter reset logic
- Counter increments when current run doesn't beat high water mark
- Counter resets to 0 when current run beats high water mark
- Counter triggers failure after 10 consecutive non-improving runs
- OuterLoopTracker tracks retry count and maxes at 5
- ModelEscalator selects appropriate model based on retry count
"""

from __future__ import annotations

import pytest

from stronghold.builders.nested_loop import MasonTestTracker, OuterLoopTracker, ModelEscalator


class TestMasonTestTracker:
    """Sophisticated test tracking for Mason's inner build loop."""

    def test_initializes_with_zero_state(self) -> None:
        tracker = MasonTestTracker()
        assert tracker.high_water_mark == 0
        assert tracker.stall_counter == 0
        assert tracker.has_failed is False

    def test_updates_high_water_mark_on_improvement(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        assert tracker.high_water_mark == 10
        assert tracker.stall_counter == 0

    def test_resets_counter_when_beating_high_water_mark(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        tracker.record_test_result(passing_count=8)
        assert tracker.stall_counter == 1
        tracker.record_test_result(passing_count=15)
        assert tracker.high_water_mark == 15
        assert tracker.stall_counter == 0

    def test_increments_counter_on_no_improvement(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        tracker.record_test_result(passing_count=5)
        tracker.record_test_result(passing_count=8)
        tracker.record_test_result(passing_count=10)
        assert tracker.stall_counter == 3

    def test_triggers_failure_after_10_consecutive_stalls(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        for _ in range(9):
            tracker.record_test_result(passing_count=5)
        assert tracker.has_failed is False
        tracker.record_test_result(passing_count=8)
        assert tracker.has_failed is True
        assert tracker.stall_counter == 10

    def test_does_not_fail_before_10_stalls(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        for _ in range(9):
            tracker.record_test_result(passing_count=5)
        assert tracker.has_failed is False

    def test_same_count_as_high_water_mark_counts_as_stall(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        tracker.record_test_result(passing_count=10)
        assert tracker.stall_counter == 1

    def test_serializes_state_for_persistence(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        state = tracker.to_dict()
        assert state["high_water_mark"] == 10
        assert state["stall_counter"] == 0

    def test_restores_state_from_dict(self) -> None:
        state = {"high_water_mark": 15, "stall_counter": 3, "has_failed": False}
        tracker = MasonTestTracker.from_dict(state)
        assert tracker.high_water_mark == 15
        assert tracker.stall_counter == 3
        assert tracker.has_failed is False

    def test_failed_state_persists_across_deserialization(self) -> None:
        tracker = MasonTestTracker()
        tracker.record_test_result(passing_count=10)
        for _ in range(10):
            tracker.record_test_result(passing_count=5)
        state = tracker.to_dict()
        restored = MasonTestTracker.from_dict(state)
        assert restored.has_failed is True


class TestOuterLoopTracker:
    """Outer loop retry tracking with max 5 failures."""

    def test_initializes_with_zero_failures(self) -> None:
        tracker = OuterLoopTracker()
        assert tracker.failure_count == 0
        assert tracker.max_failures == 5
        assert tracker.should_signal_admin is False

    def test_increments_failure_count_on_record(self) -> None:
        tracker = OuterLoopTracker()
        tracker.record_failure()
        assert tracker.failure_count == 1
        tracker.record_failure()
        assert tracker.failure_count == 2

    def test_signals_admin_after_max_failures(self) -> None:
        tracker = OuterLoopTracker()
        for _ in range(4):
            tracker.record_failure()
        assert tracker.should_signal_admin is False
        tracker.record_failure()
        assert tracker.should_signal_admin is True

    def test_does_not_signal_admin_before_max_failures(self) -> None:
        tracker = OuterLoopTracker()
        for _ in range(4):
            tracker.record_failure()
        assert tracker.should_signal_admin is False

    def test_resets_on_success(self) -> None:
        tracker = OuterLoopTracker()
        tracker.record_failure()
        tracker.record_failure()
        tracker.record_success()
        assert tracker.failure_count == 0
        assert tracker.should_signal_admin is False

    def test_serializes_state(self) -> None:
        tracker = OuterLoopTracker()
        tracker.record_failure()
        state = tracker.to_dict()
        assert state["failure_count"] == 1
        assert state["max_failures"] == 5

    def test_restores_state_from_dict(self) -> None:
        state = {"failure_count": 3, "max_failures": 5}
        tracker = OuterLoopTracker.from_dict(state)
        assert tracker.failure_count == 3


class TestModelEscalator:
    """Model selection based on retry count for outer loop escalation."""

    def test_initial_uses_first_model(self) -> None:
        escalator = ModelEscalator()
        model = escalator.select_model(retry_count=0)
        assert model == "gemini-2.5-pro"

    def test_escalates_on_each_retry(self) -> None:
        escalator = ModelEscalator()
        assert escalator.select_model(retry_count=0) == "gemini-2.5-pro"
        assert escalator.select_model(retry_count=1) == "gemini-2.5-flash"
        assert escalator.select_model(retry_count=2) == "mistral-large"
        assert escalator.select_model(retry_count=3) == "claude-3-opus"

    def test_caps_at_most_powerful_model(self) -> None:
        escalator = ModelEscalator()
        model_5 = escalator.select_model(retry_count=5)
        model_10 = escalator.select_model(retry_count=10)
        assert model_5 == model_10

    def test_supports_custom_model_priority(self) -> None:
        custom_priority = ["model-a", "model-b", "model-c"]
        escalator = ModelEscalator(model_priority=custom_priority)
        assert escalator.select_model(retry_count=0) == "model-a"
        assert escalator.select_model(retry_count=1) == "model-b"
        assert escalator.select_model(retry_count=10) == "model-c"

    def test_returns_none_for_empty_priority_list(self) -> None:
        escalator = ModelEscalator(model_priority=[])
        assert escalator.select_model(retry_count=0) is None
