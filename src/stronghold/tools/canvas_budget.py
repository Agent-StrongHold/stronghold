"""Cost forecasting + per-scope budget tracking (spec §31).

`DefaultCostForecaster` produces deterministic `CostForecast` objects from
a small price table; `InMemoryBudgetStore` reserves + commits spend per
scope (USER / DOCUMENT / TENANT) with atomic decrement and period reset.

Approval thresholds (spec §31):
  < $0.01            → AUTO
  $0.01–$0.10        → AUTO
  $0.10–$1.00        → SESSION_CONFIRM
  $1.00–$10.00       → REQUIRES_APPROVAL
  ≥ $10.00           → TYPED_CONFIRM
  ≥ $100.00          → BLOCKED (admin override required)
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

from stronghold.types.canvas_design import (
    Budget,
    BudgetPeriod,
    BudgetScope,
    BudgetStatus,
    CostForecast,
)
from stronghold.types.errors import (
    BudgetExceededError,
    ForecastUnavailableError,
)

# ---------------------------------------------------------------------------
# Approval thresholds
# ---------------------------------------------------------------------------


class ApprovalDecision(StrEnum):
    """Outcome of the per-action cost gate."""

    AUTO = "auto"  # below interactive thresholds
    SESSION_CONFIRM = "session_confirm"  # confirm once per session
    REQUIRES_APPROVAL = "requires_approval"  # modal each time
    TYPED_CONFIRM = "typed_confirm"  # user types "yes"
    BLOCKED = "blocked"  # > $100 or budget exceeded


_APPROVAL_TIERS: tuple[tuple[Decimal, ApprovalDecision], ...] = (
    (Decimal("0.10"), ApprovalDecision.AUTO),
    (Decimal("1.00"), ApprovalDecision.SESSION_CONFIRM),
    (Decimal("10.00"), ApprovalDecision.REQUIRES_APPROVAL),
    (Decimal("100.00"), ApprovalDecision.TYPED_CONFIRM),
)


def approval_for(amount_usd: Decimal) -> ApprovalDecision:
    """Decision based purely on cost — does NOT consult budget state."""
    for ceiling, decision in _APPROVAL_TIERS:
        if amount_usd < ceiling:
            return decision
    return ApprovalDecision.BLOCKED


# ---------------------------------------------------------------------------
# Cost forecaster
# ---------------------------------------------------------------------------


# Price table mapping (action, model) → cost-per-call USD. Real prices come
# from `config/model_prices.yaml`; this default lets the in-memory tests run
# without external config.
_DEFAULT_PRICES: dict[tuple[str, str], Decimal] = {
    ("generate", "gemini-2.5-flash-image"): Decimal("0.00"),  # free tier
    ("generate", "flux.1-schnell"): Decimal("0.00"),  # free promo
    ("generate", "flux.1.1-pro"): Decimal("0.04"),
    ("generate", "imagen-4-ultra"): Decimal("0.00"),
    ("inpaint", "flux.1-kontext-pro"): Decimal("0.04"),
    ("inpaint", "sdxl-inpaint"): Decimal("0.02"),
    ("controlnet_generate", "sdxl-controlnet"): Decimal("0.06"),
    ("upscale", "real-esrgan-4x"): Decimal("0.01"),
    ("variation", "flux.1-schnell"): Decimal("0.00"),
}

# Per-action priority list. First entry wins unless its free tier is exhausted.
_DEFAULT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "generate": (
        "gemini-2.5-flash-image",
        "flux.1-schnell",
        "flux.1.1-pro",
    ),
    "inpaint": ("flux.1-kontext-pro", "sdxl-inpaint"),
    "controlnet_generate": ("sdxl-controlnet",),
    "upscale": ("real-esrgan-4x",),
    "variation": ("flux.1-schnell",),
}


class DefaultCostForecaster:
    """Deterministic forecast from a static price table.

    A `cache_lookup` callable can be passed to detect cache hits (returns
    True if the inputs were already produced); the default treats every
    call as a miss.
    """

    def __init__(
        self,
        *,
        prices: dict[tuple[str, str], Decimal] | None = None,
        candidates: dict[str, tuple[str, ...]] | None = None,
        free_tier_remaining: dict[str, int] | None = None,
        is_cached: object | None = None,
    ) -> None:
        self._prices = dict(prices) if prices is not None else dict(_DEFAULT_PRICES)
        self._candidates = dict(candidates) if candidates is not None else dict(_DEFAULT_CANDIDATES)
        self._free_tier_remaining = (
            dict(free_tier_remaining) if free_tier_remaining is not None else {}
        )
        self._is_cached = is_cached

    def forecast(
        self,
        action: str,
        args: dict[str, Any],
        *,
        cache_lookup: bool = True,
    ) -> CostForecast:
        candidates = self._candidates.get(action)
        if not candidates:
            raise ForecastUnavailableError(f"no candidates registered for action={action!r}")

        # Pick the first candidate that has either: a non-zero price, OR a
        # free tier with capacity remaining.
        selected: str | None = None
        for model in candidates:
            price = self._prices.get((action, model))
            if price is None:
                continue
            free_remaining = self._free_tier_remaining.get(model)
            if price == Decimal("0") and free_remaining is not None and free_remaining <= 0:
                # Free model whose free tier is exhausted: skip
                continue
            selected = model
            break
        if selected is None:
            # Fall through: pick the most expensive candidate as a safe default
            # (per spec §31 edge case 3: forecast over-estimates rather than
            # under-estimates when uncertain).
            sorted_candidates = sorted(
                candidates,
                key=lambda m: self._prices.get((action, m), Decimal("9999")),
                reverse=True,
            )
            selected = sorted_candidates[0]

        price = self._prices.get((action, selected), Decimal("9999"))
        cache_hit = False
        if cache_lookup and self._is_cached is not None:
            cache_hit = bool(self._is_cached(action, args))  # type: ignore[operator]
        cost = Decimal("0") if cache_hit else price
        return CostForecast(
            action=action,
            selected_model=selected,
            estimated_cost_usd=cost,
            cache_hit=cache_hit,
        )

    def consume_free_tier(self, model: str, amount: int = 1) -> None:
        """Decrement the free-tier counter for a model (call after a real spend)."""
        if model in self._free_tier_remaining:
            self._free_tier_remaining[model] = max(0, self._free_tier_remaining[model] - amount)


# ---------------------------------------------------------------------------
# Budget store
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _next_reset(period: BudgetPeriod, *, now: datetime | None = None) -> datetime | None:
    now = now or _now()
    if period is BudgetPeriod.DAILY:
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return tomorrow
    if period is BudgetPeriod.MONTHLY:
        if now.month == 12:
            return datetime(now.year + 1, 1, 1, tzinfo=UTC)
        return datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    return None  # LIFETIME


@dataclasses.dataclass
class _Spend:
    """Mutable accumulator under one (scope, scope_id, tenant_id) key."""

    spent_usd: Decimal = Decimal("0")
    period_start: datetime = dataclasses.field(default_factory=_now)


class InMemoryBudgetStore:
    """Per-(scope, scope_id) Budget + spend tracking, tenant-isolated.

    The Protocol uses `amount_usd: str` for transport simplicity; this
    implementation parses to `Decimal` internally and never uses `float`.
    """

    def __init__(self) -> None:
        # tenant_id → (scope, scope_id) → Budget
        self._budgets: dict[str, dict[tuple[BudgetScope, str], Budget]] = {}
        # tenant_id → (scope, scope_id) → _Spend
        self._spend: dict[str, dict[tuple[BudgetScope, str], _Spend]] = {}

    async def upsert_budget(self, budget: Budget, *, tenant_id: str) -> None:
        bucket = self._budgets.setdefault(tenant_id, {})
        bucket[(budget.scope, budget.scope_id)] = budget

    async def get_state(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        budget = self._budget_for(tenant_id, scope, scope_id)
        if budget is None:
            return {}
        spend = self._spend_for(tenant_id, scope, scope_id, budget)
        remaining = budget.cap_usd - spend.spent_usd
        pct = int((spend.spent_usd / budget.cap_usd) * 100) if budget.cap_usd > 0 else 0
        if remaining <= 0:
            status = BudgetStatus.BLOCKED
        elif pct >= budget.warn_at_pct:
            status = BudgetStatus.WARN
        else:
            status = BudgetStatus.OK
        return {
            "budget_id": budget.id,
            "spent_usd": str(spend.spent_usd),
            "remaining_usd": str(remaining),
            "pct_used": pct,
            "status": status.value,
            "reset_at": _next_reset(budget.period, now=spend.period_start),
        }

    async def reserve(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
        amount_usd: str,
    ) -> BudgetStatus:
        amount = Decimal(amount_usd)
        budget = self._budget_for(tenant_id, scope, scope_id)
        if budget is None:
            return BudgetStatus.OK  # no budget = unbounded
        spend = self._spend_for(tenant_id, scope, scope_id, budget)
        if spend.spent_usd + amount > budget.cap_usd:
            if budget.hard_block:
                raise BudgetExceededError(
                    f"reserve {amount} would exceed {scope.value} cap "
                    f"{budget.cap_usd} (already spent {spend.spent_usd})"
                )
            return BudgetStatus.BLOCKED
        # Atomic optimistic decrement
        spend.spent_usd += amount
        # Status decision uses the AFTER-reserve totals
        pct = int((spend.spent_usd / budget.cap_usd) * 100) if budget.cap_usd > 0 else 0
        if spend.spent_usd >= budget.cap_usd:
            return BudgetStatus.BLOCKED
        if pct >= budget.warn_at_pct:
            return BudgetStatus.WARN
        return BudgetStatus.OK

    async def commit(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
        amount_usd: str,
    ) -> None:
        """Reconcile actual vs reserved.

        For the in-memory store we treat amount_usd as the *actual* spend;
        callers must adjust by the reserved delta themselves. Per spec §31
        the production reconciliation cron handles this — for tests we
        accept either positive (more than reserved) or negative (refund).
        """
        amount = Decimal(amount_usd)
        budget = self._budget_for(tenant_id, scope, scope_id)
        if budget is None:
            return
        spend = self._spend_for(tenant_id, scope, scope_id, budget)
        spend.spent_usd += amount
        if spend.spent_usd < Decimal("0"):
            spend.spent_usd = Decimal("0")

    # ── extras (test ergonomics) ────────────────────────────────────────

    def reset_period(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
    ) -> None:
        """Force a period reset (cron equivalent)."""
        budget = self._budget_for(tenant_id, scope, scope_id)
        if budget is None:
            return
        spend = self._spend_for(tenant_id, scope, scope_id, budget)
        spend.spent_usd = Decimal("0")
        spend.period_start = _now()

    # ── helpers ────────────────────────────────────────────────────────

    def _budget_for(
        self,
        tenant_id: str,
        scope: BudgetScope,
        scope_id: str,
    ) -> Budget | None:
        return self._budgets.get(tenant_id, {}).get((scope, scope_id))

    def _spend_for(
        self,
        tenant_id: str,
        scope: BudgetScope,
        scope_id: str,
        budget: Budget,
    ) -> _Spend:
        bucket = self._spend.setdefault(tenant_id, {})
        spend = bucket.get((scope, scope_id))
        if spend is None:
            spend = _Spend()
            bucket[(scope, scope_id)] = spend
        # Auto-reset if the period has rolled over
        next_reset_at = _next_reset(budget.period, now=spend.period_start)
        if next_reset_at is not None and _now() >= next_reset_at:
            spend.spent_usd = Decimal("0")
            spend.period_start = _now()
        return spend


# ---------------------------------------------------------------------------
# Multi-scope gate (spec §31: most-restrictive wins)
# ---------------------------------------------------------------------------


async def cost_gate(
    forecast: CostForecast,
    *,
    tenant_id: str,
    user_id: str | None,
    document_id: str | None,
    store: InMemoryBudgetStore,
) -> ApprovalDecision:
    """Run the cost gate against all applicable budget scopes.

    Returns an ApprovalDecision; raises BudgetExceededError if any scope
    rejects (hard block).
    """
    if forecast.cache_hit:
        return ApprovalDecision.AUTO

    # Reserve in scope precedence order: TENANT → DOCUMENT → USER. The
    # most-restrictive scope short-circuits the check via BudgetExceededError.
    targets: list[tuple[BudgetScope, str]] = []
    if document_id is not None:
        targets.append((BudgetScope.DOCUMENT, document_id))
    if user_id is not None:
        targets.append((BudgetScope.USER, user_id))
    targets.append((BudgetScope.TENANT, tenant_id))

    amount = str(forecast.estimated_cost_usd)
    for scope, scope_id in targets:
        await store.reserve(scope, scope_id, tenant_id=tenant_id, amount_usd=amount)
    return approval_for(forecast.estimated_cost_usd)
