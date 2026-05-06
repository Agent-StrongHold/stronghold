Feature: Cost forecasts and budgets
  Every paid action carries a forecast; per-user/per-doc/per-tenant budgets
  gate at thresholds; reconciliation on actuals.

  See ../31-cost-budget.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a price table loaded for the standard models

  @p0 @critical
  Scenario: Cost forecast for inpaint returns selected model and estimate
    When I forecast inpaint with prompt P, mask M
    Then the forecast names a selected_model from the candidates
    And estimated_cost_usd is the price for that model and request size
    And cache_hit is false (assuming uncached input)

  @p0 @critical
  Scenario: Cache hit forecast cost is zero
    Given a previously executed inpaint with the same input
    When I forecast it again
    Then forecast.cache_hit is true
    And estimated_cost_usd is 0

  @p0
  Scenario Outline: Approval thresholds gate costs
    Given alice's approval thresholds use defaults
    When the forecast cost is <cost>
    Then the cost gate decision is <decision>

    Examples:
      | cost  | decision           |
      | 0.005 | OK                 |
      | 0.05  | OK                 |
      | 0.50  | SESSION_CONFIRM    |
      | 5.00  | REQUIRES_APPROVAL  |
      | 50.0  | TYPED_CONFIRM      |
      | 150.0 | BLOCKED            |

  @p0
  Scenario: Daily user budget caps spending
    Given alice has a DAILY budget cap of $5
    And alice has spent $4.90 today
    When alice forecasts a $0.20 action
    Then cost_gate returns BLOCKED
    And the BudgetState says "would exceed daily cap"

  @p0
  Scenario: Concurrent calls racing the same budget atomically decrement
    Given a budget with $0.10 remaining
    And two callers each forecast a $0.06 action
    When both attempt to gate concurrently
    Then exactly one succeeds and one is BLOCKED with remaining=0 reason

  @p0
  Scenario: Free-tier exhaustion falls through to next candidate model
    Given gemini-2.5-flash-image free tier is exhausted today
    When I forecast generate at draft tier
    Then the selected_model is the next candidate (e.g. flux-schnell)
    And the UI surface shows the change reason

  @p0
  Scenario: Reconciliation records delta when actual differs from forecast
    Given a forecast of $0.04 for model X
    And the actual response cost is $0.05
    When the reconciliation cron runs
    Then a CostActual exists linking to the forecast
    And delta is +0.01

  @p0 @security
  Scenario: Cross-tenant budget read denied
    Given bob in tenant "globex" has a budget B
    When alice (tenant "acme") tries budget_state on B
    Then BudgetExceededError or PermissionDeniedError is raised

  @p0 @security
  Scenario: User cannot raise a budget owned by another user
    Given carol's USER-scope budget cap is $5
    When alice tries to budget_update carol's budget
    Then PermissionDeniedError is raised

  @p0
  Scenario: Multi-scope: most-restrictive wins
    Given alice's USER cap = $100, document cap = $5, tenant cap = $1000
    When alice forecasts a $6 action
    Then BLOCKED with reason mentioning the document scope

  @p0
  Scenario: Budget reset rolls over at period boundary
    Given alice's DAILY budget reset at midnight
    When the cron crosses midnight
    Then BudgetState.spent_usd is 0
    And status is OK

  @p0
  Scenario: Refund adjusts CostActual and budget retroactively
    Given a successful $0.10 spend recorded
    When the provider refunds $0.05 (partial failure)
    Then CostActual is updated to actual_cost_usd $0.05
    And the budget remaining_usd increases by $0.05

  @p0
  Scenario: Forecast unavailability defaults to maximum candidate cost
    Given a model not in the price table
    When I forecast an action using that model
    Then the forecast uses the max candidate cost as a safe default
    And a warning is recorded

  @p0
  Scenario: Tenant admin can raise but not lower a user's cap below their setting
    Given alice's user cap = $20
    When tenant admin raises alice's cap to $50
    Then alice's effective cap is $50
    When tenant admin attempts to lower below $20
    Then PermissionDeniedError is raised
