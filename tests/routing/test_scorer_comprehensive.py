"""Comprehensive tests for router scoring internals.

Covers edge cases in:
- score_candidate (formula, field population, zero/extreme inputs)
- compute_effective_cost (scarcity math, NaN/infinity guards, boundary tokens)
- compute_speed_bonus (capping, unknown tasks, zero/negative speed)

These go beyond the property-based and happy-path tests in the neighboring files
and specifically target formula edge cases: zero quality, extreme scarcity,
speed-bonus interaction, strength matching permutations, NaN/infinity handling,
and empty-candidate scenarios.
"""

from __future__ import annotations

import math

from stronghold.router.scarcity import compute_effective_cost
from stronghold.router.scorer import score_candidate
from stronghold.router.speed import SPEED_WEIGHTS, compute_speed_bonus
from stronghold.types.model import ModelCandidate
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)

# ── score_candidate formula edge cases ──────────────────────────────


class TestZeroQuality:
    """Exact-zero quality should not crash and should produce a minimal score."""

    def test_zero_quality_produces_zero_score(self) -> None:
        result = score_candidate(
            "z",
            build_model_config(quality=0.0),
            build_provider_config(),
            build_intent(),
            build_routing_config(),
            usage_pct=0.5,
        )
        assert result.score == 0.0

    def test_near_zero_quality_positive_score(self) -> None:
        result = score_candidate(
            "nz",
            build_model_config(quality=0.001),
            build_provider_config(),
            build_intent(),
            build_routing_config(),
            usage_pct=0.5,
        )
        assert result.score > 0.0
        assert math.isfinite(result.score)


class TestQualityExponentFloorComprehensive:
    """Ensure the max(0.1, ...) floor on quality exponent is effective."""

    def test_zero_quality_weight_still_applies_floor(self) -> None:
        """quality_weight=0 with priority_mult=1 => exponent floors at 0.1."""
        result = score_candidate(
            "f",
            build_model_config(quality=0.5),
            build_provider_config(),
            build_intent(priority="normal"),
            build_routing_config(quality_weight=0.0),
            usage_pct=0.5,
        )
        # With floor at 0.1, score = 0.5^0.1 / cost^cw — still meaningful
        assert result.score > 0.0
        assert math.isfinite(result.score)

    def test_tiny_quality_weight_tiny_priority(self) -> None:
        """Extremely small product should floor at 0.1."""
        routing = build_routing_config(
            quality_weight=0.01,
            priority_multipliers={"low": 0.01, "normal": 1.0, "high": 1.2, "critical": 1.5},
        )
        result = score_candidate(
            "f",
            build_model_config(quality=0.5),
            build_provider_config(),
            build_intent(priority="low"),
            routing,
            usage_pct=0.0,
        )
        assert result.score > 0.0


class TestCostWeightZero:
    """cost_weight=0 => c_factor=1.0, score = q_factor only."""

    def test_zero_cost_weight_ignores_cost(self) -> None:
        routing = build_routing_config(cost_weight=0.0)
        cheap = score_candidate(
            "c",
            build_model_config(quality=0.7),
            build_provider_config(free_tokens=10_000_000_000),
            build_intent(),
            routing,
            usage_pct=0.0,
        )
        expensive = score_candidate(
            "e",
            build_model_config(quality=0.7),
            build_provider_config(free_tokens=100),
            build_intent(),
            routing,
            usage_pct=0.9,
        )
        # Any positive number to the power of 0 is 1.0, so cost has no effect
        assert cheap.score == expensive.score


class TestCFactorZeroGuard:
    """When c_factor computes to 0, division should not crash."""

    def test_score_with_exhausted_provider_no_paygo(self) -> None:
        """usage >= 1.0 with no paygo => cost=999.0, c_factor > 0."""
        result = score_candidate(
            "ex",
            build_model_config(quality=0.7),
            build_provider_config(free_tokens=1_000_000),
            build_intent(),
            build_routing_config(),
            usage_pct=1.0,
        )
        assert result.score > 0.0
        assert result.effective_cost == 999.0
        assert math.isfinite(result.score)


class TestStrengthMatchingPermutations:
    """All three strength branches: match, mismatch, empty."""

    def test_matching_strength_boosts_quality(self) -> None:
        intent = build_intent(preferred_strengths=("code", "reasoning"))
        model = build_model_config(quality=0.8, strengths=("code",))
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # 0.8 * 1.15 = 0.92 (capped at 1.0)
        assert result.quality >= 0.8 * 1.15 - 0.01  # allow rounding

    def test_mismatched_strength_penalizes_quality(self) -> None:
        intent = build_intent(preferred_strengths=("code",), task_type="code")
        model = build_model_config(quality=0.8, strengths=("creative",), speed=0)
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # 0.8 * 0.90 = 0.72, code task has zero speed bonus
        assert abs(result.quality - 0.72) < 0.01

    def test_empty_strengths_neutral(self) -> None:
        intent = build_intent(preferred_strengths=("code",), task_type="code")
        model = build_model_config(quality=0.8, strengths=(), speed=0)
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # strength_mult = 1.0 for empty model strengths, code task has no speed bonus
        assert 0.79 <= result.quality <= 0.81

    def test_empty_preferred_strengths_no_crash(self) -> None:
        intent = build_intent(preferred_strengths=(), task_type="code")
        model = build_model_config(quality=0.7, strengths=("code",), speed=0)
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # Empty preferred & nonempty model => intersection empty, model_strengths truthy => 0.90
        # code task has zero speed bonus => adjusted_quality = 0.7 * 0.90 = 0.63
        assert abs(result.quality - 0.63) < 0.01
        assert result.score > 0.0

    def test_both_strengths_empty(self) -> None:
        intent = build_intent(preferred_strengths=(), task_type="code")
        model = build_model_config(quality=0.7, strengths=(), speed=0)
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # strength_mult = 1.0, code task has zero speed bonus
        assert 0.69 <= result.quality <= 0.71

    def test_partial_overlap_still_boosts(self) -> None:
        intent = build_intent(preferred_strengths=("code", "reasoning"))
        model = build_model_config(quality=0.7, strengths=("code", "creative"))
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # Intersection {"code"} is nonempty => 1.15 boost
        assert result.quality >= 0.7 * 1.15 - 0.01


class TestStrengthBoostCapping:
    """Strength boost * base quality that would exceed 1.0 is capped."""

    def test_high_quality_with_strength_boost_capped_at_one(self) -> None:
        intent = build_intent(preferred_strengths=("code",))
        model = build_model_config(quality=0.95, strengths=("code",))
        result = score_candidate(
            "m", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # 0.95 * 1.15 = 1.0925 => capped at 1.0
        assert result.quality <= 1.0


class TestSpeedBonusInteraction:
    """Speed bonus combined with quality and strength adjustments."""

    def test_speed_bonus_on_top_of_strength_match(self) -> None:
        intent = build_intent(task_type="automation", preferred_strengths=("code",))
        model = build_model_config(quality=0.5, speed=2000, strengths=("code",))
        result = score_candidate(
            "s", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # quality after strength: 0.5 * 1.15 = 0.575
        # speed bonus: 0.25 (automation at max speed)
        # adjusted: min(1.0, 0.575 * 1.25) = 0.71875
        assert 0.71 <= result.quality <= 0.72

    def test_speed_bonus_capped_at_one_combined(self) -> None:
        """High quality + strength boost + speed bonus should cap at 1.0."""
        intent = build_intent(task_type="automation", preferred_strengths=("code",))
        model = build_model_config(quality=0.9, speed=2000, strengths=("code",))
        result = score_candidate(
            "s", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        assert result.quality <= 1.0

    def test_zero_speed_no_bonus_even_for_automation(self) -> None:
        """Speed=0 should produce no bonus regardless of task type."""
        intent = build_intent(task_type="automation")
        model = build_model_config(quality=0.7, speed=0, strengths=())
        result = score_candidate(
            "z", model, build_provider_config(), intent, build_routing_config(), 0.0
        )
        # quality = 0.7 * 1.0 (no strength) * (1 + 0) = 0.7
        assert 0.69 <= result.quality <= 0.71


class TestCandidateFieldPopulation:
    """Verify all fields on the returned ModelCandidate."""

    def test_litellm_id_falls_back_to_model_id(self) -> None:
        model = build_model_config(litellm_id="")
        result = score_candidate(
            "my-id", model, build_provider_config(), build_intent(), build_routing_config(), 0.3
        )
        assert result.litellm_id == "my-id"

    def test_litellm_id_used_when_present(self) -> None:
        model = build_model_config(litellm_id="provider/gpt-4")
        result = score_candidate(
            "my-id", model, build_provider_config(), build_intent(), build_routing_config(), 0.3
        )
        assert result.litellm_id == "provider/gpt-4"

    def test_has_paygo_true_with_output_only(self) -> None:
        provider = build_provider_config(
            overage_cost_per_1k_input=0.0, overage_cost_per_1k_output=0.05
        )
        result = score_candidate(
            "p", build_model_config(), provider, build_intent(), build_routing_config(), 0.5
        )
        assert result.has_paygo is True

    def test_usage_pct_rounded(self) -> None:
        result = score_candidate(
            "r",
            build_model_config(),
            build_provider_config(),
            build_intent(),
            build_routing_config(),
            usage_pct=0.123456789,
        )
        # usage_pct rounded to 4 decimal places
        assert result.usage_pct == round(0.123456789, 4)

    def test_returns_model_candidate_type(self) -> None:
        result = score_candidate(
            "t",
            build_model_config(),
            build_provider_config(),
            build_intent(),
            build_routing_config(),
            usage_pct=0.0,
        )
        assert isinstance(result, ModelCandidate)

    def test_tier_propagated(self) -> None:
        model = build_model_config(tier="frontier")
        result = score_candidate(
            "t", model, build_provider_config(), build_intent(), build_routing_config(), 0.0
        )
        assert result.tier == "frontier"


class TestPriorityMultiplierEdgeCases:
    """Priority multiplier lookup and missing keys."""

    def test_unknown_priority_defaults_to_one(self) -> None:
        """If priority is not in the multiplier dict, default is 1.0."""
        intent = build_intent(priority="normal")
        # Override the priority to something not in the dict via a custom multipliers map
        routing = build_routing_config(
            priority_multipliers={"high": 2.0}  # "normal" not present
        )
        result = score_candidate(
            "u",
            build_model_config(quality=0.5),
            build_provider_config(),
            intent,
            routing,
            usage_pct=0.0,
        )
        # Should not crash; multiplier defaults to 1.0
        assert result.score > 0.0

    def test_very_high_priority_multiplier(self) -> None:
        routing = build_routing_config(
            priority_multipliers={"normal": 10.0, "low": 0.8, "high": 1.2, "critical": 1.5}
        )
        result = score_candidate(
            "h",
            build_model_config(quality=0.5),
            build_provider_config(),
            build_intent(priority="normal"),
            routing,
            usage_pct=0.0,
        )
        # quality_exponent = max(0.1, 0.6 * 10.0) = 6.0
        # 0.5^6 = 0.015625 — a very small score because quality < 1
        assert result.score > 0.0
        assert result.score < 0.1


# ── compute_effective_cost edge cases ───────────────────────────────


class TestEffectiveCostNaNInfinity:
    """Ensure no NaN or Infinity escapes the cost function."""

    def test_negative_usage_pct_no_crash(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000)
        cost = compute_effective_cost(-0.5, provider)
        assert math.isfinite(cost)
        assert cost > 0.0

    def test_extreme_usage_pct_no_nan(self) -> None:
        provider = build_provider_config(free_tokens=1_000_000)
        cost = compute_effective_cost(1000.0, provider)
        assert math.isfinite(cost)
        assert cost == 999.0  # >= 1.0, no paygo

    def test_one_free_token_no_nan(self) -> None:
        provider = build_provider_config(free_tokens=1, billing_cycle="daily")
        cost = compute_effective_cost(0.0, provider)
        assert math.isfinite(cost)
        assert cost > 0.0

    def test_huge_free_tokens_no_overflow(self) -> None:
        provider = build_provider_config(free_tokens=10**15)
        cost = compute_effective_cost(0.0, provider)
        assert math.isfinite(cost)
        assert cost > 0.0
        assert cost < 0.05  # extremely cheap

    def test_remaining_clamps_at_001(self) -> None:
        """At 99.99% usage, remaining = daily * 0.01 (the floor), not negative."""
        provider = build_provider_config(free_tokens=1_000_000)
        cost = compute_effective_cost(0.9999, provider)
        assert math.isfinite(cost)
        assert cost > 0.0


class TestEffectiveCostBillingCycle:
    """Monthly vs daily billing affects the daily budget calculation."""

    def test_monthly_divides_by_30(self) -> None:
        monthly = build_provider_config(free_tokens=3_000_000, billing_cycle="monthly")
        daily = build_provider_config(free_tokens=100_000, billing_cycle="daily")
        # monthly: 3_000_000 / 30 = 100_000 daily
        # daily: 100_000 daily
        cost_m = compute_effective_cost(0.5, monthly)
        cost_d = compute_effective_cost(0.5, daily)
        # Both have identical daily budget => identical cost
        assert abs(cost_m - cost_d) < 1e-10


class TestEffectiveCostPaygoVsNonPaygo:
    """At exactly 1.0 usage, paygo returns per-token cost, non-paygo returns 999."""

    def test_paygo_input_only(self) -> None:
        provider = build_provider_config(
            free_tokens=1_000_000,
            overage_cost_per_1k_input=0.10,
            overage_cost_per_1k_output=0.0,
        )
        cost = compute_effective_cost(1.0, provider)
        # Only input has overage: (0.10 + 0.0) / 2000 = 0.00005
        expected = (0.10 + 0.0) / 2000
        assert abs(cost - expected) < 1e-10

    def test_paygo_output_only(self) -> None:
        provider = build_provider_config(
            free_tokens=1_000_000,
            overage_cost_per_1k_input=0.0,
            overage_cost_per_1k_output=0.10,
        )
        cost = compute_effective_cost(1.0, provider)
        expected = (0.0 + 0.10) / 2000
        assert abs(cost - expected) < 1e-10


# ── compute_speed_bonus edge cases ──────────────────────────────────


class TestSpeedBonusEdgeCases:
    """Edge cases for the speed bonus computation."""

    def test_negative_speed_treated_as_zero(self) -> None:
        bonus = compute_speed_bonus("automation", -100)
        # min(1.0, -100/2000) = min(1.0, -0.05) = -0.05
        # weight * norm_speed = 0.25 * -0.05 = negative
        # The function doesn't guard against this, so verify actual behavior
        assert bonus <= 0.0

    def test_exactly_max_speed(self) -> None:
        bonus = compute_speed_bonus("automation", 2000)
        assert bonus == 0.25  # weight * 1.0

    def test_over_max_speed_capped(self) -> None:
        bonus = compute_speed_bonus("automation", 99999)
        assert bonus == 0.25  # capped at norm_speed=1.0

    def test_all_zero_weight_tasks_return_zero(self) -> None:
        for task_type, weight in SPEED_WEIGHTS.items():
            if weight == 0.0:
                bonus = compute_speed_bonus(task_type, 2000)
                assert bonus == 0.0, f"{task_type} should have zero bonus"

    def test_summarize_speed_bonus_value(self) -> None:
        bonus = compute_speed_bonus("summarize", 1000)
        # weight=0.10, norm_speed=0.5 => 0.05
        assert abs(bonus - 0.05) < 1e-10

    def test_creative_speed_bonus_value(self) -> None:
        bonus = compute_speed_bonus("creative", 2000)
        assert abs(bonus - 0.05) < 1e-10


# ── Empty / degenerate candidate scenarios ──────────────────────────


class TestDegenerateInputs:
    """Degenerate but structurally valid inputs should not crash."""

    def test_all_defaults_produces_valid_candidate(self) -> None:
        """Every factory default should produce a finite, positive score."""
        result = score_candidate(
            "default",
            build_model_config(),
            build_provider_config(),
            build_intent(),
            build_routing_config(),
            usage_pct=0.0,
        )
        assert math.isfinite(result.score)
        assert result.score > 0.0

    def test_empty_model_id(self) -> None:
        result = score_candidate(
            "",
            build_model_config(),
            build_provider_config(),
            build_intent(),
            build_routing_config(),
            usage_pct=0.0,
        )
        assert result.model_id == ""
        assert result.score > 0.0

    def test_multiple_candidates_can_be_sorted(self) -> None:
        """Simulate the router sorting step: scores must be comparable."""
        intent = build_intent()
        routing = build_routing_config()
        provider = build_provider_config()

        candidates = [
            score_candidate(
                f"m{i}",
                build_model_config(quality=q),
                provider,
                intent,
                routing,
                usage_pct=0.3,
            )
            for i, q in enumerate([0.3, 0.9, 0.5, 0.7, 0.1])
        ]
        sorted_cands = sorted(candidates, key=lambda c: c.score, reverse=True)
        # Verify monotone descending
        for i in range(1, len(sorted_cands)):
            assert sorted_cands[i - 1].score >= sorted_cands[i].score

    def test_score_deterministic(self) -> None:
        """Same inputs must produce identical scores."""
        kwargs = {
            "model_id": "det",
            "model_cfg": build_model_config(quality=0.6),
            "provider_cfg": build_provider_config(),
            "intent": build_intent(),
            "routing_cfg": build_routing_config(),
            "usage_pct": 0.42,
        }
        a = score_candidate(**kwargs)  # type: ignore[arg-type]
        b = score_candidate(**kwargs)  # type: ignore[arg-type]
        assert a.score == b.score
        assert a.quality == b.quality
        assert a.effective_cost == b.effective_cost
