"""Tests for TrustTierManager — promotion/demotion with history tracking."""

from __future__ import annotations

from stronghold.security.trust_tiers import TrustTier, TrustTierManager


class TestTrustTierEnum:
    """TrustTier enum ordering and membership."""

    def test_tier_ordering(self) -> None:
        """Tiers are ordered: SKULL < T3 < T2 < T1 < T0."""
        assert TrustTier.SKULL < TrustTier.T3
        assert TrustTier.T3 < TrustTier.T2
        assert TrustTier.T2 < TrustTier.T1
        assert TrustTier.T1 < TrustTier.T0

    def test_tier_parse_from_string(self) -> None:
        """Tiers can be parsed from their string names."""
        assert TrustTier.parse("skull") is TrustTier.SKULL
        assert TrustTier.parse("t3") is TrustTier.T3
        assert TrustTier.parse("t2") is TrustTier.T2
        assert TrustTier.parse("t1") is TrustTier.T1
        assert TrustTier.parse("t0") is TrustTier.T0

    def test_tier_int_values_ascending(self) -> None:
        """Tier integer values increase with privilege level."""
        assert TrustTier.SKULL.value == 0
        assert TrustTier.T3.value == 1
        assert TrustTier.T2.value == 2
        assert TrustTier.T1.value == 3
        assert TrustTier.T0.value == 4


class TestTrustTierManagerGetTier:
    """Getting an agent's current tier."""

    def test_get_tier_default(self) -> None:
        """Unknown agents default to skull tier."""
        mgr = TrustTierManager()
        assert mgr.get_tier("unknown-agent") == "skull"

    def test_get_tier_registered(self) -> None:
        """Agents with explicitly set tiers return the correct value."""
        mgr = TrustTierManager(initial_tiers={"ranger": "t2", "forge": "skull"})
        assert mgr.get_tier("ranger") == "t2"
        assert mgr.get_tier("forge") == "skull"


class TestCanPromote:
    """Promotion eligibility rules."""

    def test_promote_skull_to_t3(self) -> None:
        """skull -> T3 is allowed (forge QA gate)."""
        mgr = TrustTierManager()
        assert mgr.can_promote("skull", "t3") is True

    def test_promote_t3_to_t2(self) -> None:
        """T3 -> T2 is allowed (successful use threshold)."""
        mgr = TrustTierManager()
        assert mgr.can_promote("t3", "t2") is True

    def test_promote_t2_to_t1(self) -> None:
        """T2 -> T1 is allowed (operator approval)."""
        mgr = TrustTierManager()
        assert mgr.can_promote("t2", "t1") is True

    def test_promote_to_t0_blocked(self) -> None:
        """Automatic promotion to T0 is never allowed."""
        mgr = TrustTierManager()
        assert mgr.can_promote("t1", "t0") is False

    def test_promote_skip_tier_blocked(self) -> None:
        """Skipping a tier (skull -> T2) is not allowed."""
        mgr = TrustTierManager()
        assert mgr.can_promote("skull", "t2") is False

    def test_promote_same_tier_blocked(self) -> None:
        """Promoting to the same tier is not allowed."""
        mgr = TrustTierManager()
        assert mgr.can_promote("t2", "t2") is False

    def test_promote_downward_blocked(self) -> None:
        """can_promote rejects downward tier changes (that's a demotion)."""
        mgr = TrustTierManager()
        assert mgr.can_promote("t1", "t3") is False


class TestPromote:
    """Actual tier promotion."""

    def test_promote_success(self) -> None:
        """Promoting an agent updates its tier and records history."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t3"})
        result = mgr.promote(
            "test-agent", "t2", reason="10 successful uses", promoted_by="operator-1"
        )
        assert result is True
        assert mgr.get_tier("test-agent") == "t2"

    def test_promote_records_history(self) -> None:
        """Promotion is recorded in the agent's history."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "skull"})
        mgr.promote("test-agent", "t3", reason="forge QA passed", promoted_by="forge")

        history = mgr.get_promotion_history("test-agent")
        assert len(history) == 1
        entry = history[0]
        assert entry["from_tier"] == "skull"
        assert entry["to_tier"] == "t3"
        assert entry["reason"] == "forge QA passed"
        assert entry["action"] == "promote"
        assert entry["promoted_by"] == "forge"
        assert "timestamp" in entry

    def test_promote_to_t0_fails(self) -> None:
        """Attempting to promote to T0 returns False and does not change tier."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t1"})
        result = mgr.promote("test-agent", "t0", reason="auto-promote", promoted_by="system")
        assert result is False
        assert mgr.get_tier("test-agent") == "t1"

    def test_promote_skip_tier_fails(self) -> None:
        """Attempting to skip tiers returns False."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "skull"})
        result = mgr.promote("test-agent", "t2", reason="skip", promoted_by="operator")
        assert result is False
        assert mgr.get_tier("test-agent") == "skull"


class TestDemote:
    """Tier demotion."""

    def test_demote_success(self) -> None:
        """Demoting an agent lowers its tier and records history."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t1"})
        result = mgr.demote("test-agent", "t3", reason="security incident")
        assert result is True
        assert mgr.get_tier("test-agent") == "t3"

    def test_demote_records_history(self) -> None:
        """Demotion is recorded with action='demote'."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t2"})
        mgr.demote("test-agent", "skull", reason="trust revoked")

        history = mgr.get_promotion_history("test-agent")
        assert len(history) == 1
        entry = history[0]
        assert entry["from_tier"] == "t2"
        assert entry["to_tier"] == "skull"
        assert entry["reason"] == "trust revoked"
        assert entry["action"] == "demote"
        assert "timestamp" in entry

    def test_demote_upward_fails(self) -> None:
        """Cannot demote to a higher tier — that's a promotion."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t3"})
        result = mgr.demote("test-agent", "t1", reason="oops")
        assert result is False
        assert mgr.get_tier("test-agent") == "t3"

    def test_demote_same_tier_fails(self) -> None:
        """Cannot demote to the same tier."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t2"})
        result = mgr.demote("test-agent", "t2", reason="no change")
        assert result is False
        assert mgr.get_tier("test-agent") == "t2"

    def test_demote_can_skip_tiers(self) -> None:
        """Demotion can skip tiers (emergency revocation)."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "t1"})
        result = mgr.demote("test-agent", "skull", reason="critical vulnerability")
        assert result is True
        assert mgr.get_tier("test-agent") == "skull"


class TestPromotionHistory:
    """History tracking across multiple operations."""

    def test_empty_history_for_unknown_agent(self) -> None:
        """Unknown agents have empty promotion history."""
        mgr = TrustTierManager()
        assert mgr.get_promotion_history("nonexistent") == []

    def test_multiple_operations_recorded_in_order(self) -> None:
        """History preserves chronological order of all operations."""
        mgr = TrustTierManager(initial_tiers={"test-agent": "skull"})
        mgr.promote("test-agent", "t3", reason="forge QA", promoted_by="forge")
        mgr.promote("test-agent", "t2", reason="10 uses", promoted_by="system")
        mgr.demote("test-agent", "t3", reason="bad behavior")

        history = mgr.get_promotion_history("test-agent")
        assert len(history) == 3
        assert history[0]["action"] == "promote"
        assert history[0]["to_tier"] == "t3"
        assert history[1]["action"] == "promote"
        assert history[1]["to_tier"] == "t2"
        assert history[2]["action"] == "demote"
        assert history[2]["to_tier"] == "t3"

    def test_history_isolated_per_agent(self) -> None:
        """Each agent has its own history — no cross-contamination."""
        mgr = TrustTierManager(initial_tiers={"agent-a": "skull", "agent-b": "t3"})
        mgr.promote("agent-a", "t3", reason="qa", promoted_by="forge")
        mgr.promote("agent-b", "t2", reason="usage", promoted_by="system")

        assert len(mgr.get_promotion_history("agent-a")) == 1
        assert len(mgr.get_promotion_history("agent-b")) == 1
        assert mgr.get_promotion_history("agent-a")[0]["to_tier"] == "t3"
        assert mgr.get_promotion_history("agent-b")[0]["to_tier"] == "t2"
