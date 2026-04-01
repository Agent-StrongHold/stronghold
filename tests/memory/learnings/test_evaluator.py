"""Tests for LearningEvaluator: A/B holdout, contradiction detection, and decay."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from stronghold.memory.learnings.evaluator import (
    CONTRADICTION_OVERLAP_THRESHOLD,
    DECAY_STEP,
    DECAY_WEIGHT_FLOOR,
    LearningEvaluator,
)
from tests.factories import build_learning


class TestShouldInject:
    """A/B holdout: ~10% of learnings withheld."""

    def test_inject_when_rng_above_holdout(self) -> None:
        """Learning injected when random value >= holdout rate."""
        # Seed RNG to produce a value above 0.10
        rng = random.Random(42)
        evaluator = LearningEvaluator(rng=rng)
        learning = build_learning(id=1)
        # With seed 42, first random() is ~0.639 — above 0.10
        assert evaluator.should_inject(learning) is True

    def test_withhold_when_rng_below_holdout(self) -> None:
        """Learning withheld when random value < holdout rate."""
        # Use a holdout rate of 1.0 so everything is withheld
        rng = random.Random(0)
        evaluator = LearningEvaluator(holdout_rate=1.0, rng=rng)
        learning = build_learning(id=1)
        assert evaluator.should_inject(learning) is False

    def test_holdout_rate_approximates_ten_percent(self) -> None:
        """Over many trials, ~10% are withheld."""
        rng = random.Random(12345)
        evaluator = LearningEvaluator(rng=rng)
        learning = build_learning(id=1)

        results = [evaluator.should_inject(learning) for _ in range(1000)]
        withheld = results.count(False)
        # Should be roughly 10% +/- 3%
        assert 70 <= withheld <= 130, f"Expected ~100 withheld, got {withheld}"

    def test_zero_holdout_always_injects(self) -> None:
        """With holdout_rate=0, every learning is injected."""
        evaluator = LearningEvaluator(holdout_rate=0.0)
        learning = build_learning(id=1)
        for _ in range(100):
            assert evaluator.should_inject(learning) is True


class TestRecordOutcomeAndEffectiveness:
    """Track A/B outcomes and compute effectiveness metrics."""

    def test_record_and_retrieve_effectiveness(self) -> None:
        """Basic: record outcomes and check rates."""
        evaluator = LearningEvaluator()

        # 3 injected: 2 success, 1 failure
        evaluator.record_outcome(1, injected=True, tool_succeeded=True)
        evaluator.record_outcome(1, injected=True, tool_succeeded=True)
        evaluator.record_outcome(1, injected=True, tool_succeeded=False)

        # 2 withheld: 1 success, 1 failure
        evaluator.record_outcome(1, injected=False, tool_succeeded=True)
        evaluator.record_outcome(1, injected=False, tool_succeeded=False)

        eff = evaluator.get_effectiveness(1)
        assert eff["injected_success_rate"] == 2 / 3
        assert eff["withheld_success_rate"] == 1 / 2
        assert eff["delta"] == (2 / 3) - (1 / 2)
        assert eff["trials"] == 5

    def test_no_outcomes_returns_zeros(self) -> None:
        """No outcomes recorded for a learning returns zero rates."""
        evaluator = LearningEvaluator()
        eff = evaluator.get_effectiveness(999)
        assert eff["injected_success_rate"] == 0.0
        assert eff["withheld_success_rate"] == 0.0
        assert eff["delta"] == 0.0
        assert eff["trials"] == 0

    def test_only_injected_outcomes(self) -> None:
        """When only injected outcomes exist, withheld rate is 0."""
        evaluator = LearningEvaluator()
        evaluator.record_outcome(1, injected=True, tool_succeeded=True)
        evaluator.record_outcome(1, injected=True, tool_succeeded=False)

        eff = evaluator.get_effectiveness(1)
        assert eff["injected_success_rate"] == 0.5
        assert eff["withheld_success_rate"] == 0.0
        assert eff["trials"] == 2

    def test_outcomes_scoped_to_learning_id(self) -> None:
        """Outcomes for different learning_ids don't mix."""
        evaluator = LearningEvaluator()
        evaluator.record_outcome(1, injected=True, tool_succeeded=True)
        evaluator.record_outcome(2, injected=True, tool_succeeded=False)

        eff1 = evaluator.get_effectiveness(1)
        eff2 = evaluator.get_effectiveness(2)
        assert eff1["injected_success_rate"] == 1.0
        assert eff2["injected_success_rate"] == 0.0


class TestDetectContradictions:
    """Find learnings with overlapping keywords but different corrections."""

    def test_detects_same_tool_overlapping_keys_different_learning(self) -> None:
        """Two learnings for the same tool with overlapping keys and different text."""
        a = build_learning(
            id=1,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom"],
            learning="use entity_id fan.bedroom_ceiling",
        )
        b = build_learning(
            id=2,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom"],
            learning="use entity_id fan.bedroom_floor",
        )
        evaluator = LearningEvaluator()
        contradictions = evaluator.detect_contradictions([a, b])
        assert len(contradictions) == 1
        assert contradictions[0] == (a, b)

    def test_no_contradiction_different_tools(self) -> None:
        """Learnings for different tools are not contradictory."""
        a = build_learning(
            id=1,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom"],
            learning="use entity_id fan.bedroom_ceiling",
        )
        b = build_learning(
            id=2,
            tool_name="web_search",
            trigger_keys=["fan", "bedroom"],
            learning="search for bedroom fan reviews",
        )
        evaluator = LearningEvaluator()
        contradictions = evaluator.detect_contradictions([a, b])
        assert len(contradictions) == 0

    def test_no_contradiction_low_overlap(self) -> None:
        """Learnings with low keyword overlap are not contradictory."""
        a = build_learning(
            id=1,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom", "ceiling"],
            learning="use fan.bedroom_ceiling",
        )
        b = build_learning(
            id=2,
            tool_name="ha_control",
            trigger_keys=["light", "kitchen", "counter"],
            learning="use light.kitchen_counter",
        )
        evaluator = LearningEvaluator()
        contradictions = evaluator.detect_contradictions([a, b])
        assert len(contradictions) == 0

    def test_no_contradiction_same_learning_text(self) -> None:
        """Learnings with identical text are not contradictory."""
        text = "use entity_id fan.bedroom_ceiling"
        a = build_learning(id=1, tool_name="ha_control", trigger_keys=["fan"], learning=text)
        b = build_learning(id=2, tool_name="ha_control", trigger_keys=["fan"], learning=text)
        evaluator = LearningEvaluator()
        contradictions = evaluator.detect_contradictions([a, b])
        assert len(contradictions) == 0

    def test_overlap_threshold_boundary(self) -> None:
        """Overlap exactly at threshold is flagged; just below is not."""
        # 2 shared out of 4 total = 0.50 overlap (at threshold)
        a = build_learning(
            id=1,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom"],
            learning="correction A",
        )
        b = build_learning(
            id=2,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom"],
            learning="correction B",
        )
        evaluator = LearningEvaluator()
        # 2/2 = 1.0 overlap — above threshold
        assert len(evaluator.detect_contradictions([a, b])) == 1

        # Now 1 shared out of 3 total = 0.33 — below threshold
        c = build_learning(
            id=3,
            tool_name="ha_control",
            trigger_keys=["fan", "kitchen"],
            learning="correction C",
        )
        d = build_learning(
            id=4,
            tool_name="ha_control",
            trigger_keys=["fan", "bedroom"],
            learning="correction D",
        )
        result = evaluator.detect_contradictions([c, d])
        # 1 shared ("fan") out of 3 unique ("fan","kitchen","bedroom") = 0.33
        assert CONTRADICTION_OVERLAP_THRESHOLD == 0.5
        assert len(result) == 0


class TestApplyDecay:
    """Reduce weight of unused learnings after inactivity period."""

    def test_decays_inactive_learning(self) -> None:
        """Learning unused for > 30 days gets weight reduced."""
        old_date = datetime.now(UTC) - timedelta(days=45)
        learning = build_learning(id=1, weight=1.0, last_used_at=old_date)

        evaluator = LearningEvaluator()
        decayed = evaluator.apply_decay([learning])

        assert len(decayed) == 1
        assert learning.weight == 1.0 - DECAY_STEP

    def test_no_decay_for_recent_learning(self) -> None:
        """Learning used recently is not decayed."""
        recent = datetime.now(UTC) - timedelta(days=5)
        learning = build_learning(id=1, weight=1.0, last_used_at=recent)

        evaluator = LearningEvaluator()
        decayed = evaluator.apply_decay([learning])

        assert len(decayed) == 0
        assert learning.weight == 1.0

    def test_decay_respects_weight_floor(self) -> None:
        """Weight never drops below DECAY_WEIGHT_FLOOR."""
        old_date = datetime.now(UTC) - timedelta(days=60)
        learning = build_learning(id=1, weight=DECAY_WEIGHT_FLOOR, last_used_at=old_date)

        evaluator = LearningEvaluator()
        decayed = evaluator.apply_decay([learning])

        assert len(decayed) == 0
        assert learning.weight == DECAY_WEIGHT_FLOOR

    def test_decay_custom_days_inactive(self) -> None:
        """Custom days_inactive parameter works."""
        old_date = datetime.now(UTC) - timedelta(days=10)
        learning = build_learning(id=1, weight=0.8, last_used_at=old_date)

        evaluator = LearningEvaluator()
        # 7 days inactive threshold — learning is 10 days old, so it decays
        decayed = evaluator.apply_decay([learning], days_inactive=7)
        assert len(decayed) == 1
        assert learning.weight == 0.7

        # 15 days inactive threshold — learning is only 10 days old, no decay
        learning2 = build_learning(id=2, weight=0.8, last_used_at=old_date)
        decayed2 = evaluator.apply_decay([learning2], days_inactive=15)
        assert len(decayed2) == 0
        assert learning2.weight == 0.8

    def test_multiple_decays_approach_floor(self) -> None:
        """Repeated decay calls reduce weight toward floor."""
        old_date = datetime.now(UTC) - timedelta(days=60)
        learning = build_learning(id=1, weight=0.5, last_used_at=old_date)

        evaluator = LearningEvaluator()
        # First decay: 0.5 -> 0.4
        evaluator.apply_decay([learning])
        assert round(learning.weight, 2) == 0.4

        # Second decay: 0.4 -> 0.3
        evaluator.apply_decay([learning])
        assert round(learning.weight, 2) == 0.3

        # Keep decaying toward floor
        evaluator.apply_decay([learning])  # 0.3 -> 0.2
        evaluator.apply_decay([learning])  # 0.2 -> 0.1 (floor)
        assert round(learning.weight, 2) == DECAY_WEIGHT_FLOOR

        # At floor: no further decay
        decayed = evaluator.apply_decay([learning])
        assert len(decayed) == 0
        assert round(learning.weight, 2) == DECAY_WEIGHT_FLOOR
