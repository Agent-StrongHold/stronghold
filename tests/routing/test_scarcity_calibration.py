"""Tests that scarcity costs interact meaningfully with quality values.

Invariants:
- Same model on two providers at different usage levels: fresh provider scores higher
- The margin is meaningful (not just epsilon)
"""

from __future__ import annotations

from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.scorer import score_candidate
from stronghold.router.selector import RouterEngine
from tests.factories import (
    build_intent,
    build_model_config,
    build_provider_config,
    build_routing_config,
)


class TestFreshProviderScoresHigher:
    """Same model quality on two providers: the one at 10% usage beats 90% usage."""

    def test_low_usage_provider_wins(self) -> None:
        intent = build_intent(task_type="chat", min_tier="small")
        config = build_routing_config()
        provider = build_provider_config(free_tokens=1_000_000_000)

        fresh = score_candidate(
            "model-fresh",
            build_model_config(quality=0.7, provider="provider_a"),
            provider,
            intent,
            config,
            usage_pct=0.10,
        )
        depleted = score_candidate(
            "model-depleted",
            build_model_config(quality=0.7, provider="provider_b"),
            provider,
            intent,
            config,
            usage_pct=0.90,
        )

        assert fresh.score > depleted.score

    def test_margin_is_meaningful(self) -> None:
        """The difference must not be trivially small."""
        intent = build_intent(task_type="chat", min_tier="small")
        config = build_routing_config()
        provider = build_provider_config(free_tokens=1_000_000_000)

        fresh = score_candidate(
            "model-fresh",
            build_model_config(quality=0.7, provider="provider_a"),
            provider,
            intent,
            config,
            usage_pct=0.10,
        )
        depleted = score_candidate(
            "model-depleted",
            build_model_config(quality=0.7, provider="provider_b"),
            provider,
            intent,
            config,
            usage_pct=0.90,
        )

        gap = fresh.score - depleted.score
        assert gap > 0.01, (
            f"Score gap between 10% and 90% usage is too small: {gap:.6f}. "
            f"Fresh={fresh.score}, Depleted={depleted.score}"
        )


class TestScarcityInRouterEngine:
    """End-to-end: RouterEngine picks the fresh provider when models are identical."""

    def test_router_prefers_fresh_provider(self) -> None:
        engine = RouterEngine(InMemoryQuotaTracker())

        models = {
            "model-on-fresh": build_model_config(
                provider="fresh_provider",
                quality=0.7,
                speed=500,
                tier="medium",
                strengths=("chat",),
                litellm_id="fresh/model",
            ),
            "model-on-depleted": build_model_config(
                provider="depleted_provider",
                quality=0.7,
                speed=500,
                tier="medium",
                strengths=("chat",),
                litellm_id="depleted/model",
            ),
        }
        providers = {
            "fresh_provider": build_provider_config(
                status="active",
                free_tokens=1_000_000_000,
            ),
            "depleted_provider": build_provider_config(
                status="active",
                free_tokens=1_000_000_000,
            ),
        }
        intent = build_intent(task_type="chat", min_tier="small")
        config = build_routing_config()

        usage_pcts = {
            "fresh_provider": 0.10,
            "depleted_provider": 0.90,
        }

        result = engine.select_with_usage(intent, models, providers, config, usage_pcts=usage_pcts)

        assert result.model_id == "model-on-fresh"
        # Verify both were scored
        assert len(result.candidates) == 2
