# 31 — Cost & Budget

**Status**: P0 / Trust phase. Layered on Stronghold's existing quota system.
**One-liner**: every paid model call carries a forecast, every Document has
a soft cap, every user has a daily/monthly limit; cost is visible at the
moment of decision, not in a billing email.

## Problem it solves

A non-technical user has no model intuition. "Generate a proof render" might
cost $0.001 (Imagen Ultra free tier) or $0.06 (Ideogram 3.0). Without
visibility, costs are surprises. With it, the user can confidently say "yes,
spend $0.12 to fix this page" and trust the agent isn't wasting money.

## Data model

```
CostForecast (frozen):
  action: str                       # "inpaint", "controlnet_generate", etc.
  candidate_models: tuple[ModelCost, ...]  # ordered by priority
  selected_model: str
  estimated_cost_usd: Decimal       # >= 0
  estimated_tokens_in: int = 0
  estimated_tokens_out: int = 0
  estimated_pixels: int = 0
  estimated_duration_seconds: int = 0
  cache_hit: bool = False           # if true, cost is 0

ModelCost (frozen):
  model: str
  cost_usd: Decimal
  free_tier_remaining: int | None   # daily quota left (e.g. Gemini Flash 500/day)
  rate_limit_remaining: int | None

CostActual (frozen):
  forecast_id: str
  actual_cost_usd: Decimal
  actual_duration_seconds: float
  actual_tokens_in: int = 0
  actual_tokens_out: int = 0
  delta: Decimal                    # actual - estimated
  audit_entry_id: str

Budget (frozen):
  scope: BudgetScope                # USER | DOCUMENT | TENANT
  scope_id: str
  period: BudgetPeriod              # DAILY | MONTHLY | LIFETIME
  cap_usd: Decimal
  warn_at_pct: int = 80
  hard_block: bool = True           # block at 100%? or warn-only
  created_at: datetime
  updated_at: datetime

BudgetState (frozen):
  budget_id: str
  spent_usd: Decimal
  remaining_usd: Decimal
  pct_used: int
  status: BudgetStatus              # OK | WARN | BLOCKED
  reset_at: datetime | None         # when DAILY/MONTHLY rolls over

BudgetPeriod, BudgetScope, BudgetStatus = StrEnums

```

## Interaction with existing Stronghold quota

Stronghold has `protocols/quota.py` with `QuotaTracker`. This subsystem:
1. **Wraps** `QuotaTracker` to expose USD-denominated views, not just token
   counts.
2. **Adds** the `Budget` and `CostForecast` data models.
3. **Routes** every call through a `cost_gate` decision point before the call
   fires.

It does NOT replace the existing token-quota machinery; it sits on top.

## Cost forecast

Every action that calls a paid model produces a `CostForecast` first:

```
def forecast(action, args, context) -> CostForecast:
    candidates = router.select(action, args)        # ordered list
    chosen = candidates[0]
    pixels = estimate_pixels(action, args)
    tokens = estimate_tokens(action, args)
    base_cost = price_for(chosen, pixels, tokens)
    cache_hit = is_cached(action, args)
    cost = Decimal("0") if cache_hit else base_cost
    return CostForecast(...)
```

Forecasts are deterministic and free (no external calls). They are accurate
to within ±15% for most providers; documented variance per model.

## Budget enforcement

Pre-call check:

```
def cost_gate(forecast, user, document) -> GateDecision:
    user_state = budget_state(USER, user.id)
    doc_state  = budget_state(DOCUMENT, document.id)
    tenant_state = budget_state(TENANT, document.tenant_id)
    for state in (user_state, doc_state, tenant_state):
        if state and state.status == BLOCKED:
            return BLOCKED with reason
        if state and state.remaining_usd < forecast.estimated_cost_usd:
            return BLOCKED with reason "would exceed cap"
    if forecast.estimated_cost_usd >= user.approval_threshold_usd:
        return REQUIRES_APPROVAL
    return OK
```

Returns `OK | REQUIRES_APPROVAL | BLOCKED` with structured reason. UI shows
the modal for `REQUIRES_APPROVAL`.

## Approval thresholds (per-user setting)

Default thresholds — the user can lower or raise per session:

| Tier | Default | Behaviour |
|---|---|---|
| < $0.01 | auto-approve | (draft tier) |
| $0.01 – $0.10 | auto-approve | (single proof render) |
| $0.10 – $1.00 | session-confirm | once per session, then auto for tier |
| $1.00 – $10 | per-action confirm | always ask |
| ≥ $10 | typed-confirm | user types "yes" |
| ≥ $100 | locked | blocked unless tenant admin overrides |

## Forecasts surface to UI

Every action button in the editor shows the live forecast:

```
[Regenerate background] $0.04 ▾ (Gemini Flash free / FLUX 1.1 Pro $0.04)
```

Hover to see the candidate model list with their costs and free-tier remaining.

## Reconciliation

Actual cost (from provider invoices / per-call response metadata) reconciled
against forecasts in a nightly job:

- Compare forecast vs actual; flag deviations > 25%
- Update price tables if drift is consistent
- Surface to user as "Da Vinci spent $4.20 today on your book; budget $10/day"

## API surface

| Action | Args | Returns |
|---|---|---|
| `cost_forecast` | `action, args, context` | CostForecast |
| `budget_create` | `scope, scope_id, period, cap_usd` | Budget |
| `budget_update` | `budget_id, fields` | Budget |
| `budget_state` | `scope, scope_id` | BudgetState |
| `cost_history` | `scope, scope_id, [period]` | CostActual list |
| `set_approval_threshold` | `user_id, tier_thresholds` | updated settings |

## Edge cases

1. **Forecast underestimates** — record delta; warn user if delta > 25%; do
   not roll back the call.
2. **Forecast overestimates** — record; budget reservation is released;
   user delight.
3. **Budget reaches 100% mid-action** — current action completes (already
   gated), subsequent actions BLOCKED until reset.
4. **Free-tier exhausted** — fall to next candidate model with cost; UI
   shows the change ("Gemini Flash free tier exhausted — switching to FLUX
   1.1 Pro at $0.04").
5. **Cache hit means zero cost** — surface clearly; teaches user that
   identical regen is free.
6. **User at multiple budget scopes** — most-restrictive wins; UI shows which
   scope blocked.
7. **Concurrent calls racing the same budget** — atomic decrement on the
   budget state row; second caller sees remaining=0 if first won.
8. **Tenant overrides user limit** — admin can raise; never lower below user
   setting (user trust).
9. **Refunded provider cost** — adjust `CostActual` retroactively; budget
   reset by the same delta.
10. **Currency** — internally USD with `Decimal`; UI may format per locale
    but no FX conversion in P0.

## Errors

- `BudgetExceededError(QuotaExhaustedError, code="BUDGET_EXCEEDED")`
- `ApprovalRequiredError(StrongholdError, code="APPROVAL_REQUIRED")` — not
  really an error; signals UI gate.
- `ForecastUnavailableError(RoutingError, code="FORECAST_UNAVAILABLE")` —
  unknown model; fall back to the maximum candidate cost.

## Test surface

- Unit: forecast determinism for known model+args; price table loaded; gate
  decision matrix.
- Integration: per-action call writes a `CostActual` linked to its
  `CostForecast`; reconciliation cron updates deltas.
- Security: cross-tenant budget read returns nothing; user cannot raise a
  budget another user owns.
- Property: sum of `CostActual` for a budget period == `BudgetState.spent`.

## Dependencies

- existing `protocols/quota.py`
- `decimal.Decimal` (stdlib) — never `float` for money
- price tables in YAML config: `config/model_prices.yaml`
