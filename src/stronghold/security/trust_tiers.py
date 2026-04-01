"""Trust tier promotion/demotion manager.

Trust tiers control what agents can do:
  Skull (Forge output, unusable) -> T3 (sandboxed, read-only) -> T2 (community/operator-approved)
  -> T1 (operator-vetted, full tools) -> T0 (built-in, never auto-promoted)

Promotion rules:
  - skull -> T3: Forge QA gate
  - T3 -> T2: N successful uses
  - T2 -> T1: Operator approval
  - T1 -> T0: NEVER automatic (built-in only)
  - Skipping tiers on promotion is forbidden

Demotion rules:
  - Any tier can demote to any lower tier (emergency revocation)
"""

from __future__ import annotations

import datetime
from enum import IntEnum


class TrustTier(IntEnum):
    """Agent trust tiers, ordered from least to most privileged."""

    SKULL = 0
    T3 = 1
    T2 = 2
    T1 = 3
    T0 = 4

    @classmethod
    def parse(cls, value: str | int) -> TrustTier:
        """Parse a string ('skull', 't3', etc.) or int to a TrustTier."""
        if isinstance(value, int):
            return cls(value)
        upper = value.upper()
        if upper not in cls.__members__:
            msg = f"Unknown trust tier: {value!r}"
            raise ValueError(msg)
        return cls.__members__[upper]


# Allowed single-step promotions: from_tier -> to_tier
_PROMOTION_STEPS: dict[TrustTier, TrustTier] = {
    TrustTier.SKULL: TrustTier.T3,
    TrustTier.T3: TrustTier.T2,
    TrustTier.T2: TrustTier.T1,
    # T1 -> T0 is intentionally absent: never auto-promote to T0
}


class TrustTierManager:
    """Manages trust tier promotion and demotion for agents.

    Tracks current tiers and maintains an audit history of all changes.
    """

    def __init__(
        self,
        *,
        initial_tiers: dict[str, str] | None = None,
    ) -> None:
        self._tiers: dict[str, TrustTier] = {}
        self._history: dict[str, list[dict[str, str]]] = {}

        if initial_tiers:
            for agent_name, tier_str in initial_tiers.items():
                self._tiers[agent_name] = TrustTier.parse(tier_str)

    def get_tier(self, agent_name: str) -> str:
        """Get the current trust tier for an agent.

        Returns 'skull' for unknown agents (safe default).
        """
        tier = self._tiers.get(agent_name, TrustTier.SKULL)
        return tier.name.lower()

    def can_promote(self, current: str, target: str) -> bool:
        """Check whether promotion from current to target tier is allowed.

        Rules:
          - Only single-step promotions are allowed
          - T0 can never be reached via promotion
          - Same-tier and downward moves are rejected
        """
        current_tier = TrustTier.parse(current)
        target_tier = TrustTier.parse(target)

        # Same tier or downward: not a promotion
        if target_tier <= current_tier:
            return False

        # T0 is never auto-promotable
        if target_tier == TrustTier.T0:
            return False

        # Only single-step promotions are allowed
        allowed_next = _PROMOTION_STEPS.get(current_tier)
        return allowed_next == target_tier

    def promote(
        self,
        agent_name: str,
        target: str,
        *,
        reason: str,
        promoted_by: str,
    ) -> bool:
        """Promote an agent to a higher trust tier.

        Returns True if promotion succeeded, False if rules prevent it.
        """
        current = self.get_tier(agent_name)
        if not self.can_promote(current, target):
            return False

        target_tier = TrustTier.parse(target)
        self._tiers[agent_name] = target_tier
        self._record(
            agent_name,
            action="promote",
            from_tier=current,
            to_tier=target,
            reason=reason,
            promoted_by=promoted_by,
        )
        return True

    def demote(
        self,
        agent_name: str,
        target: str,
        *,
        reason: str,
    ) -> bool:
        """Demote an agent to a lower trust tier.

        Demotion can skip tiers (emergency revocation).
        Returns True if demotion succeeded, False if target is not lower.
        """
        current = self.get_tier(agent_name)
        current_tier = TrustTier.parse(current)
        target_tier = TrustTier.parse(target)

        # Target must be strictly lower
        if target_tier >= current_tier:
            return False

        self._tiers[agent_name] = target_tier
        self._record(
            agent_name,
            action="demote",
            from_tier=current,
            to_tier=target,
            reason=reason,
        )
        return True

    def get_promotion_history(self, agent_name: str) -> list[dict[str, str]]:
        """Get the full promotion/demotion history for an agent.

        Returns a list of dicts with: action, from_tier, to_tier, reason,
        timestamp, and optionally promoted_by.
        """
        return list(self._history.get(agent_name, []))

    def _record(
        self,
        agent_name: str,
        *,
        action: str,
        from_tier: str,
        to_tier: str,
        reason: str,
        promoted_by: str = "",
    ) -> None:
        """Record a promotion or demotion event."""
        if agent_name not in self._history:
            self._history[agent_name] = []

        entry: dict[str, str] = {
            "action": action,
            "from_tier": from_tier,
            "to_tier": to_tier,
            "reason": reason,
            "timestamp": datetime.datetime.now(tz=datetime.UTC).isoformat(),
        }
        if promoted_by:
            entry["promoted_by"] = promoted_by

        self._history[agent_name].append(entry)
