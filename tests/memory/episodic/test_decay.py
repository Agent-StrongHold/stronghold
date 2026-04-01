"""Tests for episodic memory decay, reinforcement, and forgetting curve.

Validates the decay half-life system: observations decay fast (7d half-life),
wisdom decays glacially (3650d half-life). Weight floors enforced per tier:
regret >= 0.6, wisdom >= 0.9. Reinforcement adjusts weight by +/-0.05.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stronghold.memory.episodic.decay import (
    DECAY_HALF_LIVES,
    apply_decay_sweep,
    compute_decayed_weight,
    reinforce_memory,
)
from stronghold.types.memory import EpisodicMemory, MemoryScope, MemoryTier


def _make_memory(
    tier: MemoryTier = MemoryTier.OBSERVATION,
    weight: float = 0.5,
    created_at: datetime | None = None,
    last_accessed_at: datetime | None = None,
    memory_id: str = "mem-1",
) -> EpisodicMemory:
    """Helper to construct an EpisodicMemory with sensible defaults."""
    now = datetime.now(UTC)
    return EpisodicMemory(
        memory_id=memory_id,
        tier=tier,
        content="test memory content",
        weight=weight,
        org_id="org-1",
        team_id="team-1",
        scope=MemoryScope.AGENT,
        agent_id="agent-1",
        created_at=created_at or now,
        last_accessed_at=last_accessed_at or now,
    )


class TestComputeDecayedWeight:
    """Tests for compute_decayed_weight: 2^(-days/halflife), floored."""

    def test_no_elapsed_time_returns_original_weight(self) -> None:
        """Zero days elapsed means no decay."""
        result = compute_decayed_weight(
            original_weight=0.5,
            tier=MemoryTier.OBSERVATION,
            days_elapsed=0.0,
        )
        assert result == 0.5

    def test_observation_decays_to_half_after_one_halflife(self) -> None:
        """Observation half-life is 7 days. After 7 days, weight halves."""
        result = compute_decayed_weight(
            original_weight=0.5,
            tier=MemoryTier.OBSERVATION,
            days_elapsed=7.0,
        )
        assert abs(result - 0.25) < 1e-9

    def test_observation_decays_faster_than_wisdom(self) -> None:
        """Given the same elapsed time, observation loses more weight than wisdom."""
        obs_weight = compute_decayed_weight(
            original_weight=1.0,
            tier=MemoryTier.OBSERVATION,
            days_elapsed=30.0,
        )
        wis_weight = compute_decayed_weight(
            original_weight=1.0,
            tier=MemoryTier.WISDOM,
            days_elapsed=30.0,
        )
        assert obs_weight < wis_weight

    def test_wisdom_barely_decays_after_30_days(self) -> None:
        """Wisdom half-life is 3650d. After 30 days, virtually unchanged."""
        result = compute_decayed_weight(
            original_weight=1.0,
            tier=MemoryTier.WISDOM,
            days_elapsed=30.0,
        )
        # 2^(-30/3650) ~= 0.9943
        assert result > 0.99

    def test_regret_floor_enforced(self) -> None:
        """Regret cannot decay below 0.6, even after extreme time."""
        result = compute_decayed_weight(
            original_weight=1.0,
            tier=MemoryTier.REGRET,
            days_elapsed=100_000.0,
        )
        assert result >= 0.6

    def test_wisdom_floor_enforced(self) -> None:
        """Wisdom cannot decay below 0.9, even after extreme time."""
        result = compute_decayed_weight(
            original_weight=1.0,
            tier=MemoryTier.WISDOM,
            days_elapsed=100_000.0,
        )
        assert result >= 0.9

    def test_observation_floor_enforced(self) -> None:
        """Observation cannot decay below 0.1 (tier floor)."""
        result = compute_decayed_weight(
            original_weight=0.5,
            tier=MemoryTier.OBSERVATION,
            days_elapsed=100_000.0,
        )
        assert result >= 0.1

    def test_hypothesis_intermediate_halflife(self) -> None:
        """Hypothesis decays slower than observation but faster than lesson."""
        obs = compute_decayed_weight(0.5, MemoryTier.OBSERVATION, 14.0)
        hyp = compute_decayed_weight(0.5, MemoryTier.HYPOTHESIS, 14.0)
        les = compute_decayed_weight(0.5, MemoryTier.LESSON, 14.0)
        assert obs < hyp < les

    def test_all_tiers_have_halflife(self) -> None:
        """Every MemoryTier has a decay half-life entry."""
        for tier in MemoryTier:
            assert tier in DECAY_HALF_LIVES, f"Missing half-life for {tier}"


class TestReinforceMemory:
    """Tests for reinforce_memory: +delta, bounded to tier ceiling."""

    def test_reinforce_increases_weight(self) -> None:
        """Reinforcement adds delta to weight."""
        mem = _make_memory(tier=MemoryTier.OBSERVATION, weight=0.3)
        result = reinforce_memory(mem, delta=0.05)
        assert result.weight == 0.35

    def test_reinforce_clamped_to_tier_ceiling(self) -> None:
        """Observation ceiling is 0.5. Weight cannot exceed it."""
        mem = _make_memory(tier=MemoryTier.OBSERVATION, weight=0.48)
        result = reinforce_memory(mem, delta=0.05)
        assert result.weight == 0.5

    def test_reinforce_increments_reinforcement_count(self) -> None:
        """Each reinforce call increments the reinforcement counter."""
        mem = _make_memory(tier=MemoryTier.LESSON, weight=0.7)
        result = reinforce_memory(mem, delta=0.05)
        assert result.reinforcement_count == mem.reinforcement_count + 1

    def test_reinforce_updates_last_accessed_at(self) -> None:
        """Reinforcement updates last_accessed_at to now."""
        old_time = datetime(2025, 1, 1, tzinfo=UTC)
        mem = _make_memory(
            tier=MemoryTier.LESSON,
            weight=0.7,
            last_accessed_at=old_time,
        )
        result = reinforce_memory(mem, delta=0.05)
        assert result.last_accessed_at > old_time

    def test_negative_delta_decreases_weight(self) -> None:
        """Negative delta (contradiction) decreases weight."""
        mem = _make_memory(tier=MemoryTier.LESSON, weight=0.7)
        result = reinforce_memory(mem, delta=-0.05)
        assert abs(result.weight - 0.65) < 1e-9

    def test_negative_delta_clamped_to_floor(self) -> None:
        """Regret floor is 0.6. Weight cannot go below it."""
        mem = _make_memory(tier=MemoryTier.REGRET, weight=0.62)
        result = reinforce_memory(mem, delta=-0.05)
        assert result.weight == 0.6

    def test_reinforce_preserves_memory_identity(self) -> None:
        """All non-weight fields are preserved."""
        mem = _make_memory(
            tier=MemoryTier.OPINION,
            weight=0.5,
            memory_id="keep-me",
        )
        mem.content = "important content"
        mem.org_id = "org-99"
        result = reinforce_memory(mem, delta=0.05)
        assert result.memory_id == "keep-me"
        assert result.content == "important content"
        assert result.org_id == "org-99"
        assert result.tier == MemoryTier.OPINION


class TestApplyDecaySweep:
    """Tests for apply_decay_sweep: batch decay across a list of memories."""

    def test_sweep_reduces_weights(self) -> None:
        """Sweep applies decay to all memories based on elapsed time."""
        old_time = datetime.now(UTC) - timedelta(days=14)
        memories = [
            _make_memory(
                tier=MemoryTier.OBSERVATION,
                weight=0.5,
                last_accessed_at=old_time,
                memory_id="obs-1",
            ),
            _make_memory(
                tier=MemoryTier.LESSON,
                weight=0.8,
                last_accessed_at=old_time,
                memory_id="les-1",
            ),
        ]
        results = apply_decay_sweep(memories)
        # Observation decayed more than lesson
        assert results[0].weight < 0.5
        assert results[1].weight < 0.8
        assert results[0].weight < results[1].weight

    def test_sweep_skips_deleted_memories(self) -> None:
        """Deleted memories are returned unchanged."""
        old_time = datetime.now(UTC) - timedelta(days=30)
        mem = _make_memory(
            tier=MemoryTier.OBSERVATION,
            weight=0.5,
            last_accessed_at=old_time,
        )
        mem.deleted = True
        results = apply_decay_sweep([mem])
        assert results[0].weight == 0.5
        assert results[0].deleted is True

    def test_sweep_respects_floors(self) -> None:
        """Even after sweep, weight floors are enforced."""
        ancient_time = datetime.now(UTC) - timedelta(days=365_000)
        memories = [
            _make_memory(
                tier=MemoryTier.REGRET,
                weight=1.0,
                last_accessed_at=ancient_time,
                memory_id="regret-1",
            ),
            _make_memory(
                tier=MemoryTier.WISDOM,
                weight=1.0,
                last_accessed_at=ancient_time,
                memory_id="wisdom-1",
            ),
        ]
        results = apply_decay_sweep(memories)
        assert results[0].weight >= 0.6  # regret floor
        assert results[1].weight >= 0.9  # wisdom floor

    def test_sweep_empty_list(self) -> None:
        """Sweep on empty list returns empty list."""
        assert apply_decay_sweep([]) == []

    def test_sweep_preserves_order(self) -> None:
        """Output order matches input order."""
        now = datetime.now(UTC)
        old = now - timedelta(days=7)
        memories = [
            _make_memory(memory_id="first", last_accessed_at=old),
            _make_memory(memory_id="second", last_accessed_at=old),
            _make_memory(memory_id="third", last_accessed_at=old),
        ]
        results = apply_decay_sweep(memories)
        assert [r.memory_id for r in results] == ["first", "second", "third"]

    def test_sweep_uses_custom_reference_time(self) -> None:
        """Sweep accepts a reference time instead of now."""
        created = datetime(2025, 1, 1, tzinfo=UTC)
        ref_time = datetime(2025, 1, 8, tzinfo=UTC)  # 7 days later
        mem = _make_memory(
            tier=MemoryTier.OBSERVATION,
            weight=0.5,
            last_accessed_at=created,
        )
        results = apply_decay_sweep([mem], reference_time=ref_time)
        # One half-life: 0.5 * 0.5 = 0.25
        assert abs(results[0].weight - 0.25) < 1e-9
