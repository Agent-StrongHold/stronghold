"""Tests for canary deployment manager: staged rollout with auto-rollback.

Covers: canary creation, stage advancement, traffic splitting, rollback
on errors, metrics collection, timeout/auto-rollback, multi-tenant isolation,
list_active/list_rollbacks, rollback history cap, and edge cases.
"""

from __future__ import annotations

import time

from stronghold.skills.canary import (
    _STAGE_ORDER,
    _STAGE_TRAFFIC,
    CanaryDeployment,
    CanaryManager,
    CanaryStage,
)


def _make_manager(
    error_threshold: float = 0.1,
    min_requests: int = 5,
    stage_duration: float = 0.0,
) -> CanaryManager:
    """Build a CanaryManager with test-friendly defaults."""
    return CanaryManager(
        error_threshold=error_threshold,
        min_requests_per_stage=min_requests,
        stage_duration_secs=stage_duration,
    )


def _exhaust_stage(
    mgr: CanaryManager,
    skill: str,
    n: int,
    *,
    success: bool = True,
    org_id: str = "",
) -> None:
    """Record *n* results (all success or all failure) for a given skill."""
    for _ in range(n):
        mgr.record_result(skill, success=success, org_id=org_id)


class TestCanaryDeploymentDataclass:
    """Verify CanaryDeployment computed properties."""

    def test_error_rate_zero_requests(self) -> None:
        dep = CanaryDeployment(skill_name="s")
        assert dep.error_rate == 0.0

    def test_error_rate_with_errors(self) -> None:
        dep = CanaryDeployment(skill_name="s")
        dep.total_requests = 10
        dep.errors = 3
        assert dep.error_rate == 0.3

    def test_traffic_pct_per_stage(self) -> None:
        for stage, expected_pct in _STAGE_TRAFFIC.items():
            dep = CanaryDeployment(skill_name="s", stage=stage)
            assert dep.traffic_pct == expected_pct, f"Stage {stage} expected {expected_pct}"

    def test_traffic_pct_default_is_canary(self) -> None:
        dep = CanaryDeployment(skill_name="s")
        assert dep.stage == CanaryStage.CANARY
        assert dep.traffic_pct == 0.05


class TestCanaryCreation:
    """Test start_canary and get_deployment."""

    def test_start_canary_returns_deployment(self) -> None:
        mgr = _make_manager()
        dep = mgr.start_canary("skill_a", old_version=1, new_version=2)
        assert dep.skill_name == "skill_a"
        assert dep.old_version == 1
        assert dep.new_version == 2
        assert dep.stage == CanaryStage.CANARY

    def test_start_canary_stores_deployment(self) -> None:
        mgr = _make_manager()
        mgr.start_canary("skill_a", 1, 2)
        retrieved = mgr.get_deployment("skill_a")
        assert retrieved is not None
        assert retrieved.skill_name == "skill_a"

    def test_start_canary_with_org_id(self) -> None:
        mgr = _make_manager()
        mgr.start_canary("skill_a", 1, 2, org_id="org_x")
        assert mgr.get_deployment("skill_a", org_id="org_x") is not None
        # Not visible without org_id
        assert mgr.get_deployment("skill_a") is None

    def test_start_canary_overwrites_existing(self) -> None:
        mgr = _make_manager()
        mgr.start_canary("s", 1, 2)
        mgr.start_canary("s", 2, 3)
        dep = mgr.get_deployment("s")
        assert dep is not None
        assert dep.new_version == 3

    def test_get_deployment_nonexistent(self) -> None:
        mgr = _make_manager()
        assert mgr.get_deployment("nope") is None


class TestTrafficSplitting:
    """Test should_use_new_version traffic routing."""

    def test_no_deployment_returns_false(self) -> None:
        mgr = _make_manager()
        assert not mgr.should_use_new_version("nonexistent", org_id="org")

    def test_no_org_id_returns_false(self) -> None:
        """C14: empty org_id always returns False to prevent cross-tenant leakage."""
        mgr = _make_manager()
        mgr.start_canary("s", 1, 2)
        assert not mgr.should_use_new_version("s", org_id="")

    def test_full_stage_always_routes_to_new(self) -> None:
        """At FULL stage (100%), every request should use new version."""
        mgr = _make_manager()
        dep = mgr.start_canary("s", 1, 2, org_id="org")
        dep.stage = CanaryStage.FULL
        # 100 attempts should all return True at 100% traffic
        results = [mgr.should_use_new_version("s", org_id="org") for _ in range(100)]
        assert all(results)

    def test_canary_stage_sends_some_traffic(self) -> None:
        """At CANARY stage (5%), probability is low -- run many samples."""
        mgr = _make_manager()
        mgr.start_canary("s", 1, 2, org_id="org")
        results = [mgr.should_use_new_version("s", org_id="org") for _ in range(2000)]
        pct = sum(results) / len(results)
        # 5% target, accept 1%..15% to avoid flaky tests
        assert 0.01 < pct < 0.15, f"Expected ~5% canary traffic, got {pct:.1%}"


class TestMetricsCollection:
    """Test record_result and metrics tracking."""

    def test_record_success_increments_total(self) -> None:
        mgr = _make_manager()
        dep = mgr.start_canary("s", 1, 2)
        mgr.record_result("s", success=True)
        assert dep.total_requests == 1
        assert dep.errors == 0

    def test_record_failure_increments_errors(self) -> None:
        mgr = _make_manager()
        dep = mgr.start_canary("s", 1, 2)
        mgr.record_result("s", success=False)
        assert dep.total_requests == 1
        assert dep.errors == 1

    def test_record_result_nonexistent_is_noop(self) -> None:
        mgr = _make_manager()
        # Should not raise
        mgr.record_result("ghost", success=True)

    def test_error_rate_accumulation(self) -> None:
        mgr = _make_manager()
        dep = mgr.start_canary("s", 1, 2)
        for i in range(10):
            mgr.record_result("s", success=(i % 5 != 0))  # 2 failures out of 10
        assert dep.total_requests == 10
        assert dep.errors == 2
        assert dep.error_rate == 0.2


class TestPromotion:
    """Test stage advancement through check_promotion_or_rollback."""

    def test_advance_from_canary_to_partial(self) -> None:
        mgr = _make_manager(min_requests=5, stage_duration=0.0)
        dep = mgr.start_canary("s", 1, 2)
        dep.stage_started_at = time.time() - 1.0
        _exhaust_stage(mgr, "s", 5)
        result = mgr.check_promotion_or_rollback("s")
        assert result == "advance"
        advanced = mgr.get_deployment("s")
        assert advanced is not None
        assert advanced.stage == CanaryStage.PARTIAL

    def test_advance_resets_counters(self) -> None:
        mgr = _make_manager(min_requests=3, stage_duration=0.0)
        dep = mgr.start_canary("s", 1, 2)
        dep.stage_started_at = time.time() - 1.0
        _exhaust_stage(mgr, "s", 3)
        mgr.check_promotion_or_rollback("s")
        advanced = mgr.get_deployment("s")
        assert advanced is not None
        assert advanced.total_requests == 0
        assert advanced.errors == 0

    def test_full_promotion_through_all_stages(self) -> None:
        mgr = _make_manager(min_requests=1, stage_duration=0.0)
        mgr.start_canary("s", 1, 2)
        expected_stages = [CanaryStage.PARTIAL, CanaryStage.MAJORITY, CanaryStage.FULL]

        for expected_stage in expected_stages:
            dep_active = mgr.get_deployment("s")
            assert dep_active is not None
            dep_active.stage_started_at = time.time() - 1.0
            mgr.record_result("s", success=True)
            result = mgr.check_promotion_or_rollback("s")
            assert result == "advance"
            dep_active = mgr.get_deployment("s")
            assert dep_active is not None
            assert dep_active.stage == expected_stage

        # Final advance from FULL -> complete
        dep_active = mgr.get_deployment("s")
        assert dep_active is not None
        dep_active.stage_started_at = time.time() - 1.0
        mgr.record_result("s", success=True)
        result = mgr.check_promotion_or_rollback("s")
        assert result == "complete"
        assert mgr.get_deployment("s") is None

    def test_hold_when_no_deployment(self) -> None:
        mgr = _make_manager()
        assert mgr.check_promotion_or_rollback("ghost") == "hold"

    def test_hold_when_insufficient_requests(self) -> None:
        mgr = _make_manager(min_requests=100, stage_duration=0.0)
        dep = mgr.start_canary("s", 1, 2)
        dep.stage_started_at = time.time() - 1.0
        _exhaust_stage(mgr, "s", 5)
        assert mgr.check_promotion_or_rollback("s") == "hold"

    def test_hold_when_stage_duration_not_elapsed(self) -> None:
        mgr = _make_manager(min_requests=1, stage_duration=9999.0)
        mgr.start_canary("s", 1, 2)
        mgr.record_result("s", success=True)
        # Duration hasn't passed even though we have enough requests
        assert mgr.check_promotion_or_rollback("s") == "hold"


class TestRollback:
    """Test automatic rollback on high error rates."""

    def test_rollback_when_error_rate_exceeds_threshold(self) -> None:
        mgr = _make_manager(error_threshold=0.1, min_requests=10)
        mgr.start_canary("s", 1, 2)
        # 5/10 = 50% error rate >> 10% threshold
        for i in range(10):
            mgr.record_result("s", success=(i % 2 == 0))
        result = mgr.check_promotion_or_rollback("s")
        assert result == "rollback"
        assert mgr.get_deployment("s") is None

    def test_rollback_not_triggered_below_min_requests(self) -> None:
        mgr = _make_manager(error_threshold=0.1, min_requests=100)
        mgr.start_canary("s", 1, 2)
        # All failures, but not enough requests to trigger rollback
        _exhaust_stage(mgr, "s", 5, success=False)
        assert mgr.check_promotion_or_rollback("s") == "hold"

    def test_rollback_at_exact_threshold_does_not_roll_back(self) -> None:
        """Error rate must *exceed* threshold, not equal it.

        At exactly the threshold (0.1 == 0.1), the `> threshold` check is false
        so no rollback. If stage duration is met, the `<= threshold` check passes
        and it advances instead.
        """
        mgr = _make_manager(error_threshold=0.1, min_requests=10, stage_duration=0.0)
        dep = mgr.start_canary("s", 1, 2)
        dep.stage_started_at = time.time() - 1.0
        # Exactly 10% error rate: 1 error in 10 requests
        mgr.record_result("s", success=False)
        for _ in range(9):
            mgr.record_result("s", success=True)
        # error_rate == 0.1, threshold is 0.1 -- NOT rolled back, but advanced
        result = mgr.check_promotion_or_rollback("s")
        assert result == "advance"

    def test_rollback_just_above_threshold(self) -> None:
        """Error rate just above threshold triggers rollback."""
        mgr = _make_manager(error_threshold=0.1, min_requests=10)
        mgr.start_canary("s", 1, 2)
        # 2 errors in 10 requests = 20% > 10%
        for i in range(10):
            mgr.record_result("s", success=(i >= 2))
        result = mgr.check_promotion_or_rollback("s")
        assert result == "rollback"

    def test_rollback_records_metadata(self) -> None:
        mgr = _make_manager(error_threshold=0.1, min_requests=5)
        mgr.start_canary("s", 1, 2, org_id="org_x")
        _exhaust_stage(mgr, "s", 5, success=False, org_id="org_x")
        mgr.check_promotion_or_rollback("s", org_id="org_x")
        rollbacks = mgr.list_rollbacks()
        assert len(rollbacks) == 1
        rb = rollbacks[0]
        assert rb["skill_name"] == "s"
        assert rb["new_version"] == 2
        assert rb["stage"] == "canary"
        assert rb["error_rate"] == 1.0
        assert rb["org_id"] == "org_x"
        assert "rolled_back_at" in rb

    def test_rollback_during_later_stage(self) -> None:
        """Rollback can happen at any stage, not just canary."""
        mgr = _make_manager(error_threshold=0.1, min_requests=1, stage_duration=0.0)
        dep = mgr.start_canary("s", 1, 2)
        # Advance to PARTIAL
        dep.stage_started_at = time.time() - 1.0
        mgr.record_result("s", success=True)
        mgr.check_promotion_or_rollback("s")
        # Now at PARTIAL, trigger rollback
        dep_partial = mgr.get_deployment("s")
        assert dep_partial is not None
        assert dep_partial.stage == CanaryStage.PARTIAL
        mgr.record_result("s", success=False)
        result = mgr.check_promotion_or_rollback("s")
        assert result == "rollback"
        rollbacks = mgr.list_rollbacks()
        assert rollbacks[-1]["stage"] == "partial"


class TestRollbackHistoryCap:
    """Test that rollback history is capped to prevent unbounded memory growth."""

    def test_rollback_history_capped_at_200(self) -> None:
        mgr = _make_manager(error_threshold=0.0, min_requests=1)
        for i in range(210):
            mgr.start_canary(f"s{i}", i, i + 1)
            mgr.record_result(f"s{i}", success=False)
            mgr.check_promotion_or_rollback(f"s{i}")

        # After exceeding 200, oldest entries are trimmed to 100
        rollbacks = mgr.list_rollbacks(limit=300)
        assert len(rollbacks) <= 200


class TestListActive:
    """Test list_active returns correct summaries."""

    def test_list_active_empty(self) -> None:
        mgr = _make_manager()
        assert mgr.list_active() == []

    def test_list_active_shows_deployments(self) -> None:
        mgr = _make_manager()
        mgr.start_canary("s1", 1, 2)
        mgr.start_canary("s2", 3, 4)
        active = mgr.list_active()
        assert len(active) == 2
        names = {d["skill_name"] for d in active}
        assert names == {"s1", "s2"}

    def test_list_active_includes_metrics(self) -> None:
        mgr = _make_manager()
        mgr.start_canary("s1", 1, 2)
        mgr.record_result("s1", success=True)
        mgr.record_result("s1", success=False)
        active = mgr.list_active()
        entry = active[0]
        assert entry["total_requests"] == 2
        assert entry["errors"] == 1
        assert entry["error_rate"] == 0.5
        assert entry["stage"] == "canary"
        assert entry["traffic_pct"] == 5  # 5% as integer


class TestListRollbacks:
    """Test list_rollbacks returns recent rollback records."""

    def test_list_rollbacks_empty(self) -> None:
        mgr = _make_manager()
        assert mgr.list_rollbacks() == []

    def test_list_rollbacks_limit(self) -> None:
        mgr = _make_manager(error_threshold=0.0, min_requests=1)
        for i in range(10):
            mgr.start_canary(f"s{i}", i, i + 1)
            mgr.record_result(f"s{i}", success=False)
            mgr.check_promotion_or_rollback(f"s{i}")
        assert len(mgr.list_rollbacks(limit=3)) == 3
        assert len(mgr.list_rollbacks(limit=20)) == 10


class TestMultiTenantIsolation:
    """Canary deployments are scoped by (skill_name, org_id)."""

    def test_same_skill_different_orgs_independent(self) -> None:
        mgr = _make_manager()
        dep_a = mgr.start_canary("s", 1, 2, org_id="org_a")
        dep_b = mgr.start_canary("s", 1, 3, org_id="org_b")
        assert dep_a is not dep_b
        assert dep_a.new_version == 2
        assert dep_b.new_version == 3

    def test_record_result_scoped_to_org(self) -> None:
        mgr = _make_manager()
        mgr.start_canary("s", 1, 2, org_id="org_a")
        mgr.start_canary("s", 1, 2, org_id="org_b")
        mgr.record_result("s", success=False, org_id="org_a")
        dep_a = mgr.get_deployment("s", org_id="org_a")
        dep_b = mgr.get_deployment("s", org_id="org_b")
        assert dep_a is not None
        assert dep_b is not None
        assert dep_a.errors == 1
        assert dep_b.errors == 0

    def test_rollback_one_org_does_not_affect_other(self) -> None:
        mgr = _make_manager(error_threshold=0.1, min_requests=5)
        mgr.start_canary("s", 1, 2, org_id="org_a")
        mgr.start_canary("s", 1, 2, org_id="org_b")
        # Fail org_a
        _exhaust_stage(mgr, "s", 5, success=False, org_id="org_a")
        mgr.check_promotion_or_rollback("s", org_id="org_a")
        assert mgr.get_deployment("s", org_id="org_a") is None
        assert mgr.get_deployment("s", org_id="org_b") is not None


class TestStageOrder:
    """Verify the stage progression constants are correct."""

    def test_stage_order_is_correct(self) -> None:
        assert _STAGE_ORDER == [
            CanaryStage.CANARY,
            CanaryStage.PARTIAL,
            CanaryStage.MAJORITY,
            CanaryStage.FULL,
        ]

    def test_traffic_percentages_increase_monotonically(self) -> None:
        prev = 0.0
        for stage in _STAGE_ORDER:
            pct = _STAGE_TRAFFIC[stage]
            assert pct > prev, f"{stage} traffic {pct} not > {prev}"
            prev = pct

    def test_full_stage_is_100_percent(self) -> None:
        assert _STAGE_TRAFFIC[CanaryStage.FULL] == 1.0
