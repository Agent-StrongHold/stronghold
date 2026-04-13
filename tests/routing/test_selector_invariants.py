"""Domain invariant tests for RouterEngine model selection.

Key invariant: flipping quality_weight vs cost_weight changes which model wins.
- High quality_weight -> quality model wins
- High cost_weight -> cheap model wins
- The winner actually CHANGES when weights flip
"""

from __future__ import annotations

from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)


def _two_model_setup() -> tuple[dict, dict, str, str]:
    """Create a high-quality expensive model and a low-quality cheap model.

    Returns (models, providers, quality_model_id, cheap_model_id).
    """
    models = {
        "quality-model": build_model_config(
            provider="expensive_provider",
            quality=0.95,
            speed=100,
            tier="large",
            strengths=("code", "reasoning"),
            litellm_id="expensive/quality",
        ),
        "cheap-model": build_model_config(
            provider="cheap_provider",
            quality=0.40,
            speed=500,
            tier="large",
            strengths=("code", "chat"),
            litellm_id="cheap/model",
        ),
    }
    providers = {
        "expensive_provider": build_provider_config(
            status="active",
            free_tokens=1_000_000,
            billing_cycle="monthly",
        ),
        "cheap_provider": build_provider_config(
            status="active",
            free_tokens=10_000_000_000,
            billing_cycle="monthly",
        ),
    }
    return models, providers, "quality-model", "cheap-model"


class TestHighQualityWeightFavorsQualityModel:
    """When quality_weight is high and cost_weight is low, quality model wins."""

    def test_quality_model_wins_with_high_quality_weight(self) -> None:
        engine = RouterEngine(InMemoryQuotaTracker())
        models, providers, quality_id, _cheap_id = _two_model_setup()
        intent = build_intent(task_type="code", min_tier="small")
        config = build_routing_config(quality_weight=0.95, cost_weight=0.05)

        result = engine.select_with_usage(intent, models, providers, config, usage_pcts={})

        assert result.model_id == quality_id


class TestHighCostWeightFavorsCheapModel:
    """When cost_weight is high and quality_weight is low, cheap model wins."""

    def test_cheap_model_wins_with_high_cost_weight(self) -> None:
        engine = RouterEngine(InMemoryQuotaTracker())
        models, providers, _quality_id, cheap_id = _two_model_setup()
        intent = build_intent(task_type="code", min_tier="small")
        config = build_routing_config(quality_weight=0.05, cost_weight=0.95)

        result = engine.select_with_usage(intent, models, providers, config, usage_pcts={})

        assert result.model_id == cheap_id


class TestWinnerChangesWhenWeightsFlip:
    """The selected model must actually CHANGE when weights are flipped."""

    def test_different_winners_for_flipped_weights(self) -> None:
        engine = RouterEngine(InMemoryQuotaTracker())
        models, providers, _, _ = _two_model_setup()
        intent = build_intent(task_type="code", min_tier="small")

        quality_biased = build_routing_config(quality_weight=0.95, cost_weight=0.05)
        cost_biased = build_routing_config(quality_weight=0.05, cost_weight=0.95)

        quality_result = engine.select_with_usage(
            intent, models, providers, quality_biased, usage_pcts={}
        )
        cost_result = engine.select_with_usage(
            intent, models, providers, cost_biased, usage_pcts={}
        )

        assert quality_result.model_id != cost_result.model_id, (
            f"Expected different winners but both selected {quality_result.model_id}. "
            f"Quality-biased score={quality_result.score}, "
            f"Cost-biased score={cost_result.score}"
        )

    def test_scores_diverge_meaningfully(self) -> None:
        """The score gap between the two models should be meaningful, not epsilon."""
        engine = RouterEngine(InMemoryQuotaTracker())
        models, providers, _, _ = _two_model_setup()
        intent = build_intent(task_type="code", min_tier="small")

        quality_biased = build_routing_config(quality_weight=0.95, cost_weight=0.05)

        result = engine.select_with_usage(intent, models, providers, quality_biased, usage_pcts={})

        # With 2 candidates, the winner and runner-up should have different scores
        assert len(result.candidates) == 2
        winner_score = result.candidates[0].score
        runner_up_score = result.candidates[1].score
        gap = abs(winner_score - runner_up_score)
        assert gap > 0.01, (
            f"Score gap too small: {gap:.6f}. Winner={winner_score}, Runner-up={runner_up_score}"
        )
