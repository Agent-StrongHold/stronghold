"""Episodic memory decay: forgetting curve with tier-based half-lives.

Implements exponential decay: weight = original * 2^(-days/halflife).
Weight floors per tier ensure structurally unforgettable memories:
  - REGRET floor: 0.6 (painful lessons persist)
  - WISDOM floor: 0.9 (hard-won knowledge survives)

Half-lives range from 7 days (OBSERVATION) to 3650 days (WISDOM),
so observations fade in weeks while wisdom endures for years.

Design principle #4: "Memory must forget — decay without reinforcement,
resolve contradictions explicitly, weight floors for wisdom/regrets."
"""

from __future__ import annotations

from datetime import UTC, datetime

from stronghold.memory.episodic.tiers import clamp_weight
from stronghold.types.memory import (
    WEIGHT_BOUNDS,
    EpisodicMemory,
    MemoryTier,
)

# Decay half-lives per tier in days.
# Observations evaporate quickly; wisdom is nearly permanent.
DECAY_HALF_LIVES: dict[MemoryTier, float] = {
    MemoryTier.OBSERVATION: 7.0,
    MemoryTier.HYPOTHESIS: 30.0,
    MemoryTier.OPINION: 90.0,
    MemoryTier.LESSON: 365.0,
    MemoryTier.REGRET: 730.0,
    MemoryTier.AFFIRMATION: 730.0,
    MemoryTier.WISDOM: 3650.0,
}


def compute_decayed_weight(
    original_weight: float,
    tier: MemoryTier,
    days_elapsed: float,
) -> float:
    """Compute weight after exponential decay: w * 2^(-days/halflife), floored.

    The result is clamped to the tier's weight floor so structurally
    unforgettable tiers (REGRET, WISDOM) never drop below their bounds.
    """
    halflife = DECAY_HALF_LIVES[tier]
    if days_elapsed <= 0.0:
        return original_weight
    decayed: float = original_weight * (2.0 ** (-days_elapsed / halflife))
    floor: float = WEIGHT_BOUNDS[tier][0]
    result: float = max(decayed, floor)
    return result


def reinforce_memory(
    memory: EpisodicMemory,
    delta: float = 0.05,
) -> EpisodicMemory:
    """Reinforce (or contradict) a memory by adjusting its weight.

    Positive delta = reinforcement (weight goes up).
    Negative delta = contradiction (weight goes down).
    Result is always clamped to the tier's [floor, ceiling] bounds.
    Updates last_accessed_at to now and increments reinforcement_count.
    """
    new_weight = clamp_weight(memory.tier, memory.weight + delta)
    return EpisodicMemory(
        memory_id=memory.memory_id,
        tier=memory.tier,
        content=memory.content,
        weight=new_weight,
        org_id=memory.org_id,
        team_id=memory.team_id,
        agent_id=memory.agent_id,
        user_id=memory.user_id,
        scope=memory.scope,
        source=memory.source,
        context=memory.context,
        reinforcement_count=memory.reinforcement_count + 1,
        contradiction_count=memory.contradiction_count,
        created_at=memory.created_at,
        last_accessed_at=datetime.now(UTC),
        deleted=memory.deleted,
    )


def apply_decay_sweep(
    memories: list[EpisodicMemory],
    reference_time: datetime | None = None,
) -> list[EpisodicMemory]:
    """Apply decay to a list of memories based on time since last access.

    Deleted memories are returned unchanged. Order is preserved.
    Uses reference_time as "now" (defaults to datetime.now(UTC)).
    """
    if not memories:
        return []

    now = reference_time or datetime.now(UTC)
    results: list[EpisodicMemory] = []

    for mem in memories:
        if mem.deleted:
            results.append(mem)
            continue

        elapsed = now - mem.last_accessed_at
        days = elapsed.total_seconds() / 86400.0

        new_weight = compute_decayed_weight(mem.weight, mem.tier, days)

        results.append(
            EpisodicMemory(
                memory_id=mem.memory_id,
                tier=mem.tier,
                content=mem.content,
                weight=new_weight,
                org_id=mem.org_id,
                team_id=mem.team_id,
                agent_id=mem.agent_id,
                user_id=mem.user_id,
                scope=mem.scope,
                source=mem.source,
                context=mem.context,
                reinforcement_count=mem.reinforcement_count,
                contradiction_count=mem.contradiction_count,
                created_at=mem.created_at,
                last_accessed_at=mem.last_accessed_at,
                deleted=mem.deleted,
            )
        )

    return results
