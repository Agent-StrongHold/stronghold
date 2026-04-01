"""Tests for classifier feedback loop — self-calibrating intent classification.

Covers: record_outcome, weight adjustment, bounds enforcement, accuracy tracking,
cold start, multi-keyword outcomes, and decay/convergence behavior.
"""

from __future__ import annotations

from stronghold.classifier.feedback import ClassifierFeedback

# ── Tool-to-task-type mapping used by the feedback loop ──
# These define the "ground truth" — if the user ended up using these tools,
# what task_type was it actually?
TOOL_TASK_MAP: dict[str, str] = {
    "shell": "code",
    "file_ops": "code",
    "pytest": "code",
    "ha_control": "automation",
    "device_toggle": "automation",
    "web_search": "search",
    "draw_image": "image_gen",
}


class TestRecordOutcome:
    """Recording outcomes and retrieving them."""

    def test_record_single_correct_outcome(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome(
            classified_type="code",
            actual_tools=["shell", "file_ops"],
            keywords_matched=["function", "bug"],
        )
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 1
        assert stats["correct"] == 1

    def test_record_single_incorrect_outcome(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome(
            classified_type="chat",
            actual_tools=["shell"],
            keywords_matched=["hello"],
        )
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 1
        assert stats["incorrect"] == 1

    def test_record_multiple_outcomes(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        fb.record_outcome("code", ["shell"], ["bug"])
        fb.record_outcome("chat", ["shell"], ["hello"])
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 3
        assert stats["correct"] == 2
        assert stats["incorrect"] == 1

    def test_no_tools_used_counts_as_correct(self) -> None:
        """If no tools were used, we cannot determine ground truth — count as correct."""
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("chat", [], ["hello"])
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 1
        assert stats["correct"] == 1

    def test_unknown_tools_count_as_correct(self) -> None:
        """Tools not in the map cannot disprove the classification."""
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("chat", ["some_unknown_tool"], ["hello"])
        stats = fb.get_accuracy_stats()
        assert stats["correct"] == 1


class TestWeightAdjustment:
    """Keyword weight adjustments based on outcomes."""

    def test_correct_classification_increases_weight(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        adjustments = fb.get_weight_adjustments()
        assert adjustments["function"] > 0.0

    def test_incorrect_classification_decreases_weight(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        # Start with a correct to get weight > 0, then an incorrect should reduce it
        fb.record_outcome("code", ["shell"], ["function"])
        fb.record_outcome("chat", ["shell"], ["function"])
        adjustments = fb.get_weight_adjustments()
        # Net delta: +0.1 - 0.1 = 0.0 — decreased from 0.1
        assert adjustments["function"] < 0.1

    def test_correct_increments_by_point_one(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        adjustments = fb.get_weight_adjustments()
        assert abs(adjustments["function"] - 0.1) < 1e-9

    def test_incorrect_clamps_at_zero(self) -> None:
        """A single incorrect outcome clamps the keyword weight to 0.0."""
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("chat", ["shell"], ["hello"])
        adjustments = fb.get_weight_adjustments()
        assert abs(adjustments["hello"] - 0.0) < 1e-9

    def test_mixed_outcomes_net_adjustment(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        # "function" correctly used 3 times, incorrectly 1 time → net +0.2
        fb.record_outcome("code", ["shell"], ["function"])
        fb.record_outcome("code", ["file_ops"], ["function"])
        fb.record_outcome("code", ["pytest"], ["function"])
        fb.record_outcome("chat", ["shell"], ["function"])
        adjustments = fb.get_weight_adjustments()
        assert abs(adjustments["function"] - 0.2) < 1e-9

    def test_multiple_keywords_in_single_outcome(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function", "bug", "error"])
        adjustments = fb.get_weight_adjustments()
        assert adjustments["function"] > 0.0
        assert adjustments["bug"] > 0.0
        assert adjustments["error"] > 0.0


class TestBoundsEnforcement:
    """Weight adjustments must stay within [0.0, 5.0]."""

    def test_upper_bound_enforced(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        # 60 correct outcomes → +6.0, but should be capped at 5.0
        for _ in range(60):
            fb.record_outcome("code", ["shell"], ["function"])
        adjustments = fb.get_weight_adjustments()
        assert adjustments["function"] <= 5.0

    def test_lower_bound_enforced(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        # 60 incorrect outcomes → -6.0, but should be clamped at 0.0
        for _ in range(60):
            fb.record_outcome("chat", ["shell"], ["hello"])
        adjustments = fb.get_weight_adjustments()
        assert adjustments["hello"] >= 0.0

    def test_upper_bound_exactly_five(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        for _ in range(60):
            fb.record_outcome("code", ["shell"], ["function"])
        adjustments = fb.get_weight_adjustments()
        assert abs(adjustments["function"] - 5.0) < 1e-9

    def test_lower_bound_exactly_zero(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        for _ in range(60):
            fb.record_outcome("chat", ["shell"], ["hello"])
        adjustments = fb.get_weight_adjustments()
        assert abs(adjustments["hello"] - 0.0) < 1e-9


class TestAccuracyStats:
    """Accuracy statistics computation."""

    def test_empty_stats(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 0
        assert stats["correct"] == 0
        assert stats["incorrect"] == 0
        assert stats["accuracy"] == 0.0

    def test_perfect_accuracy(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        fb.record_outcome("automation", ["ha_control"], ["light"])
        stats = fb.get_accuracy_stats()
        assert stats["accuracy"] == 1.0

    def test_zero_accuracy(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("chat", ["shell"], ["hello"])
        fb.record_outcome("code", ["ha_control"], ["function"])
        stats = fb.get_accuracy_stats()
        assert stats["accuracy"] == 0.0

    def test_partial_accuracy(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        fb.record_outcome("chat", ["shell"], ["hello"])
        stats = fb.get_accuracy_stats()
        assert abs(stats["accuracy"] - 0.5) < 1e-9

    def test_per_type_stats(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        fb.record_outcome("code", ["shell"], ["bug"])
        fb.record_outcome("code", ["ha_control"], ["error"])  # misclassified
        stats = fb.get_accuracy_stats()
        per_type = stats["per_type"]
        assert per_type["code"]["total"] == 3
        assert per_type["code"]["correct"] == 2
        assert per_type["code"]["incorrect"] == 1


class TestColdStart:
    """Behavior with no prior data."""

    def test_cold_start_adjustments_empty(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        adjustments = fb.get_weight_adjustments()
        assert adjustments == {}

    def test_cold_start_stats_zero(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 0
        assert stats["accuracy"] == 0.0

    def test_single_outcome_bootstraps(self) -> None:
        """A single outcome is enough to start producing adjustments."""
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], ["function"])
        assert len(fb.get_weight_adjustments()) == 1
        assert fb.get_accuracy_stats()["total"] == 1


class TestMajorityVoteToolResolution:
    """When multiple tools are used, majority vote determines actual task type."""

    def test_majority_vote_determines_type(self) -> None:
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        # Two code tools, one automation tool → actual = code
        fb.record_outcome("code", ["shell", "file_ops", "ha_control"], ["function"])
        stats = fb.get_accuracy_stats()
        assert stats["correct"] == 1

    def test_tie_breaks_to_classified(self) -> None:
        """On a tie, favor the classified type (benefit of the doubt)."""
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        # One code, one automation → tie → classified "code" wins
        fb.record_outcome("code", ["shell", "ha_control"], ["function"])
        stats = fb.get_accuracy_stats()
        assert stats["correct"] == 1

    def test_no_keywords_still_records(self) -> None:
        """Outcome with no keywords tracked still affects accuracy stats."""
        fb = ClassifierFeedback(tool_task_map=TOOL_TASK_MAP)
        fb.record_outcome("code", ["shell"], [])
        stats = fb.get_accuracy_stats()
        assert stats["total"] == 1
        assert stats["correct"] == 1
        # No weight adjustments since no keywords
        assert fb.get_weight_adjustments() == {}
