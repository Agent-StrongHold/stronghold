"""Spec B: LearningsConfig — RCA + promotion-threshold knobs.

Covers the LearningsConfig dataclass, default values, and the container
wiring that reads from it (promoter threshold, RCAExtractor gating).
"""

from __future__ import annotations

from typing import Any

from stronghold.container import create_container
from stronghold.types.config import LearningsConfig, StrongholdConfig


def _make_config(**overrides: Any) -> StrongholdConfig:
    """Minimal valid StrongholdConfig for container boot."""
    defaults: dict[str, Any] = {
        "providers": {
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        "models": {
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["chat"],
            },
        },
        "router_api_key": "sk-test-key-do-not-use-in-production-0000",
        "agents_dir": "",
    }
    defaults.update(overrides)
    return StrongholdConfig(**defaults)


class TestLearningsConfigDefaults:
    def test_default_rca_enabled(self) -> None:
        cfg = LearningsConfig()
        assert cfg.rca_enabled is True

    def test_default_rca_model_empty(self) -> None:
        cfg = LearningsConfig()
        assert cfg.rca_model == ""

    def test_default_promotion_threshold(self) -> None:
        cfg = LearningsConfig()
        assert cfg.promotion_threshold == 5

    def test_stronghold_config_has_learnings_field(self) -> None:
        cfg = StrongholdConfig()
        assert isinstance(cfg.learnings, LearningsConfig)

    def test_default_unchanged_invariant(self) -> None:
        """Invariant: default_unchanged — empty config == explicit default LearningsConfig."""
        implicit = StrongholdConfig()
        explicit = StrongholdConfig(learnings=LearningsConfig())
        assert implicit.learnings.rca_enabled == explicit.learnings.rca_enabled
        assert implicit.learnings.rca_model == explicit.learnings.rca_model
        assert implicit.learnings.promotion_threshold == explicit.learnings.promotion_threshold


class TestLearningsConfigContainerWiring:
    async def test_promoter_uses_configured_threshold(self) -> None:
        """The LearningPromoter picks up threshold from config, not a hardcoded 5."""
        cfg = _make_config(learnings=LearningsConfig(promotion_threshold=7))
        container = await create_container(cfg)
        assert container.learning_promoter is not None
        assert container.learning_promoter._threshold == 7

    async def test_default_threshold_still_five(self) -> None:
        """Boot with no learnings config → threshold stays at 5 (backward compat)."""
        cfg = _make_config()
        container = await create_container(cfg)
        assert container.learning_promoter._threshold == 5

    async def test_rca_enabled_by_default_wires_extractor(self) -> None:
        """With the default config, agents receive a non-None RCAExtractor."""
        cfg = _make_config()
        container = await create_container(cfg)
        # At least one agent should have the extractor wired
        extractors = [
            a._rca_extractor  # noqa: SLF001
            for a in container.agents.values()
            if a._rca_extractor is not None  # noqa: SLF001
        ]
        assert len(extractors) >= 1

    async def test_rca_disabled_skips_extractor(self) -> None:
        """Invariant: rca_disabled_means_silent — no agent gets an extractor."""
        cfg = _make_config(learnings=LearningsConfig(rca_enabled=False))
        container = await create_container(cfg)
        for agent in container.agents.values():
            assert agent._rca_extractor is None  # noqa: SLF001

    async def test_rca_model_passed_through(self) -> None:
        """Configured rca_model reaches the extractor."""
        cfg = _make_config(learnings=LearningsConfig(rca_model="gpt-4o-mini"))
        container = await create_container(cfg)
        extractors = [
            a._rca_extractor  # noqa: SLF001
            for a in container.agents.values()
            if a._rca_extractor is not None  # noqa: SLF001
        ]
        assert extractors, "expected at least one agent with RCAExtractor"
        assert extractors[0]._rca_model == "gpt-4o-mini"  # noqa: SLF001
