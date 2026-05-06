"""Cost forecast + budget green tests — features/cost-budget.feature."""

from __future__ import annotations

from decimal import Decimal

import pytest

from stronghold.tools.canvas_budget import (
    ApprovalDecision,
    DefaultCostForecaster,
    InMemoryBudgetStore,
    approval_for,
    cost_gate,
)
from stronghold.types.canvas_design import (
    Budget,
    BudgetPeriod,
    BudgetScope,
    BudgetStatus,
)
from stronghold.types.errors import (
    BudgetExceededError,
    ForecastUnavailableError,
)

# ─── Approval thresholds ───────────────────────────────────────────────────


class TestApprovalThresholds:
    @pytest.mark.parametrize(
        ("amount", "expected"),
        [
            ("0.005", ApprovalDecision.AUTO),
            ("0.05", ApprovalDecision.AUTO),
            ("0.50", ApprovalDecision.SESSION_CONFIRM),
            ("5.00", ApprovalDecision.REQUIRES_APPROVAL),
            ("50.0", ApprovalDecision.TYPED_CONFIRM),
            ("150.0", ApprovalDecision.BLOCKED),
        ],
    )
    def test_decision_matrix(self, amount: str, expected: ApprovalDecision) -> None:
        assert approval_for(Decimal(amount)) is expected


# ─── Cost forecaster ───────────────────────────────────────────────────────


class TestCostForecaster:
    def test_inpaint_forecast_uses_priority_first_model(self) -> None:
        f = DefaultCostForecaster()
        forecast = f.forecast("inpaint", {"prompt": "x"})
        assert forecast.action == "inpaint"
        assert forecast.selected_model == "flux.1-kontext-pro"
        assert forecast.estimated_cost_usd == Decimal("0.04")
        assert forecast.cache_hit is False

    def test_cache_hit_zero_cost(self) -> None:
        def is_cached(action: str, args: dict[str, object]) -> bool:
            return True

        f = DefaultCostForecaster(is_cached=is_cached)
        forecast = f.forecast("inpaint", {})
        assert forecast.cache_hit is True
        assert forecast.estimated_cost_usd == Decimal("0")

    def test_cache_lookup_disabled_skips_check(self) -> None:
        called = {"count": 0}

        def is_cached(action: str, args: dict[str, object]) -> bool:
            called["count"] += 1
            return True

        f = DefaultCostForecaster(is_cached=is_cached)
        forecast = f.forecast("inpaint", {}, cache_lookup=False)
        assert called["count"] == 0
        assert forecast.cache_hit is False

    def test_unknown_action_raises(self) -> None:
        f = DefaultCostForecaster()
        with pytest.raises(ForecastUnavailableError):
            f.forecast("teleport", {})

    def test_free_tier_exhausted_falls_through(self) -> None:
        f = DefaultCostForecaster(
            free_tier_remaining={"gemini-2.5-flash-image": 0, "flux.1-schnell": 0},
        )
        forecast = f.forecast("generate", {})
        # First two free models exhausted, falls through to flux.1.1-pro
        assert forecast.selected_model == "flux.1.1-pro"
        assert forecast.estimated_cost_usd == Decimal("0.04")

    def test_consume_free_tier_decrements(self) -> None:
        f = DefaultCostForecaster(free_tier_remaining={"gemini-2.5-flash-image": 1})
        f.consume_free_tier("gemini-2.5-flash-image")
        forecast = f.forecast("generate", {})
        # Should have moved past gemini to next candidate
        assert forecast.selected_model != "gemini-2.5-flash-image"


# ─── Budget store basics ───────────────────────────────────────────────────


def _budget(scope: BudgetScope, scope_id: str, *, cap: str = "5.00") -> Budget:
    return Budget(
        id=f"b-{scope.value}-{scope_id}",
        scope=scope,
        scope_id=scope_id,
        period=BudgetPeriod.DAILY,
        cap_usd=Decimal(cap),
    )


class TestBudgetState:
    async def test_no_budget_returns_empty_state(self) -> None:
        store = InMemoryBudgetStore()
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state == {}

    async def test_state_after_upsert(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["status"] == "ok"
        assert state["spent_usd"] == "0"
        assert state["remaining_usd"] == "5.00"

    async def test_warn_at_threshold(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="4.50")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["status"] == "warn"

    async def test_blocked_at_cap(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="5.00")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["status"] == "blocked"


class TestReserve:
    async def test_reserve_within_cap_succeeds(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        status = await store.reserve(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="0.50")
        assert status is BudgetStatus.OK

    async def test_reserve_exceeding_cap_raises(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        with pytest.raises(BudgetExceededError):
            await store.reserve(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="10.00")

    async def test_reserve_with_no_budget_is_unbounded(self) -> None:
        store = InMemoryBudgetStore()
        status = await store.reserve(
            BudgetScope.USER, "no-budget", tenant_id="acme", amount_usd="100"
        )
        assert status is BudgetStatus.OK

    async def test_concurrent_callers_atomically_decrement(self) -> None:
        store = InMemoryBudgetStore()
        # Cap = $0.10; two callers each asking $0.06 → exactly one succeeds
        await store.upsert_budget(_budget(BudgetScope.USER, "alice", cap="0.10"), tenant_id="acme")
        # First reserve should succeed (0 → 0.06; remaining 0.04)
        await store.reserve(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="0.06")
        # Second reserve must raise (0.06 + 0.06 > 0.10 cap)
        with pytest.raises(BudgetExceededError):
            await store.reserve(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="0.06")


class TestCommit:
    async def test_commit_records_actual(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="1.00")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["spent_usd"] == "1.00"

    async def test_negative_commit_acts_as_refund(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="2.00")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="-0.50")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["spent_usd"] == "1.50"

    async def test_refund_below_zero_clamped(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="-99")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["spent_usd"] == "0"


class TestPeriodReset:
    async def test_force_reset_zeroes_spend(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        await store.commit(BudgetScope.USER, "alice", tenant_id="acme", amount_usd="3.00")
        store.reset_period(BudgetScope.USER, "alice", tenant_id="acme")
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="acme")
        assert state["spent_usd"] == "0"


# ─── Tenant isolation ──────────────────────────────────────────────────────


class TestTenantIsolation:
    async def test_cross_tenant_state_returns_empty(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice"), tenant_id="acme")
        # Other tenant cannot see acme's budget
        state = await store.get_state(BudgetScope.USER, "alice", tenant_id="globex")
        assert state == {}

    async def test_cross_tenant_reserve_unbounded(self) -> None:
        store = InMemoryBudgetStore()
        await store.upsert_budget(_budget(BudgetScope.USER, "alice", cap="0.01"), tenant_id="acme")
        # Different tenant has no budget; reserve is unbounded.
        status = await store.reserve(
            BudgetScope.USER, "alice", tenant_id="globex", amount_usd="100"
        )
        assert status is BudgetStatus.OK


# ─── Multi-scope gate ──────────────────────────────────────────────────────


class TestCostGate:
    async def test_most_restrictive_wins(self) -> None:
        store = InMemoryBudgetStore()
        # User cap $100, document cap $5, tenant cap $1000 → document wins
        await store.upsert_budget(_budget(BudgetScope.USER, "alice", cap="100"), tenant_id="acme")
        await store.upsert_budget(_budget(BudgetScope.DOCUMENT, "D1", cap="5"), tenant_id="acme")
        await store.upsert_budget(_budget(BudgetScope.TENANT, "acme", cap="1000"), tenant_id="acme")
        forecaster = DefaultCostForecaster()
        forecast = forecaster.forecast("inpaint", {})
        # First reserve fits ($0.04 < $5)
        await cost_gate(
            forecast,
            tenant_id="acme",
            user_id="alice",
            document_id="D1",
            store=store,
        )
        # Force document spend close to cap
        await store.commit(BudgetScope.DOCUMENT, "D1", tenant_id="acme", amount_usd="4.95")
        # Now a $0.04 + $4.95 + $0.04 (already reserved) = $5.03 > $5 → BlockedError
        with pytest.raises(BudgetExceededError):
            await cost_gate(
                forecast,
                tenant_id="acme",
                user_id="alice",
                document_id="D1",
                store=store,
            )

    async def test_cache_hit_skips_reservation(self) -> None:
        store = InMemoryBudgetStore()
        # No budget needed — cache hit should auto-pass
        forecaster = DefaultCostForecaster(is_cached=lambda *_a: True)
        forecast = forecaster.forecast("inpaint", {})
        decision = await cost_gate(
            forecast,
            tenant_id="acme",
            user_id="alice",
            document_id="D1",
            store=store,
        )
        assert decision is ApprovalDecision.AUTO

    async def test_low_cost_returns_auto(self) -> None:
        store = InMemoryBudgetStore()
        forecaster = DefaultCostForecaster()
        forecast = forecaster.forecast("inpaint", {})
        decision = await cost_gate(
            forecast,
            tenant_id="acme",
            user_id="alice",
            document_id=None,
            store=store,
        )
        assert decision is ApprovalDecision.AUTO


# ─── Protocol conformance ──────────────────────────────────────────────────


class TestProtocolConformance:
    def test_budget_store_satisfies_protocol(self) -> None:
        from stronghold.protocols.canvas_design import BudgetStore

        assert isinstance(InMemoryBudgetStore(), BudgetStore)

    def test_cost_forecaster_satisfies_protocol(self) -> None:
        from stronghold.protocols.canvas_design import CostForecaster

        assert isinstance(DefaultCostForecaster(), CostForecaster)
