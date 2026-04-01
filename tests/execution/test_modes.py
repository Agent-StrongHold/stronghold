"""Tests for execution modes, token budget tracking, and execution context."""

from __future__ import annotations

import pytest

from stronghold.execution.modes import (
    BudgetExhaustedError,
    ExecutionContext,
    ExecutionMode,
    TokenBudget,
)


# ── ExecutionMode enum ──────────────────────────────────────────────


class TestExecutionModeEnum:
    """Verify the three execution modes exist and are usable as strings."""

    def test_best_effort_value(self) -> None:
        assert ExecutionMode.BEST_EFFORT == "best_effort"

    def test_persistent_value(self) -> None:
        assert ExecutionMode.PERSISTENT == "persistent"

    def test_supervised_value(self) -> None:
        assert ExecutionMode.SUPERVISED == "supervised"

    def test_all_modes_count(self) -> None:
        assert len(ExecutionMode) == 3

    def test_mode_is_str_enum(self) -> None:
        """Modes should be usable as plain strings (StrEnum)."""
        mode = ExecutionMode.BEST_EFFORT
        assert isinstance(mode, str)
        assert mode == "best_effort"


# ── TokenBudget ─────────────────────────────────────────────────────


class TestTokenBudget:
    """Budget tracks token usage and enforces limits."""

    def test_fresh_budget_has_zero_used(self) -> None:
        budget = TokenBudget(max_tokens=1000)
        assert budget.used_tokens == 0

    def test_can_afford_within_budget(self) -> None:
        budget = TokenBudget(max_tokens=1000)
        assert budget.can_afford(500) is True

    def test_can_afford_exact_remaining(self) -> None:
        budget = TokenBudget(max_tokens=1000, used_tokens=600)
        assert budget.can_afford(400) is True

    def test_cannot_afford_over_budget(self) -> None:
        budget = TokenBudget(max_tokens=1000, used_tokens=800)
        assert budget.can_afford(300) is False

    def test_record_increases_used(self) -> None:
        budget = TokenBudget(max_tokens=5000)
        budget.record(1200)
        assert budget.used_tokens == 1200
        budget.record(800)
        assert budget.used_tokens == 2000

    def test_record_over_budget_raises(self) -> None:
        budget = TokenBudget(max_tokens=500)
        budget.record(400)
        with pytest.raises(BudgetExhaustedError) as exc_info:
            budget.record(200)
        assert "600" in str(exc_info.value) or "exceed" in str(exc_info.value).lower()

    def test_remaining_property(self) -> None:
        budget = TokenBudget(max_tokens=1000, used_tokens=350)
        assert budget.remaining == 650

    def test_usage_pct(self) -> None:
        budget = TokenBudget(max_tokens=2000, used_tokens=500)
        assert budget.usage_pct == pytest.approx(0.25)

    def test_usage_pct_zero_max(self) -> None:
        """Edge case: zero max tokens should return 1.0 (fully exhausted)."""
        budget = TokenBudget(max_tokens=0)
        assert budget.usage_pct == pytest.approx(1.0)


# ── ExecutionContext ────────────────────────────────────────────────


class TestExecutionContext:
    """ExecutionContext holds mode, budget, decision points, and callback."""

    def test_default_mode_is_best_effort(self) -> None:
        ctx = ExecutionContext()
        assert ctx.mode == ExecutionMode.BEST_EFFORT

    def test_custom_mode(self) -> None:
        ctx = ExecutionContext(mode=ExecutionMode.SUPERVISED)
        assert ctx.mode == ExecutionMode.SUPERVISED

    def test_budget_attached(self) -> None:
        budget = TokenBudget(max_tokens=10_000)
        ctx = ExecutionContext(budget=budget)
        assert ctx.budget is budget
        assert ctx.budget.can_afford(5000) is True

    def test_decision_points_initially_empty(self) -> None:
        ctx = ExecutionContext()
        assert ctx.decision_points == []

    def test_record_decision_point(self) -> None:
        ctx = ExecutionContext(mode=ExecutionMode.SUPERVISED)
        ctx.record_decision("Should I call the external API?")
        ctx.record_decision("Proceed with file write?")
        assert len(ctx.decision_points) == 2
        assert ctx.decision_points[0] == "Should I call the external API?"
        assert ctx.decision_points[1] == "Proceed with file write?"

    def test_status_callback_default_none(self) -> None:
        ctx = ExecutionContext()
        assert ctx.status_callback is None

    def test_status_callback_stored(self) -> None:
        async def my_callback(msg: str) -> None:
            pass

        ctx = ExecutionContext(status_callback=my_callback)
        assert ctx.status_callback is my_callback


# ── BudgetExhaustedError ───────────────────────────────────────────


class TestBudgetExhaustedError:
    """BudgetExhaustedError is a StrongholdError with correct code."""

    def test_inherits_stronghold_error(self) -> None:
        from stronghold.types.errors import StrongholdError

        err = BudgetExhaustedError("over limit")
        assert isinstance(err, StrongholdError)

    def test_error_code(self) -> None:
        err = BudgetExhaustedError("ran out")
        assert err.code == "BUDGET_EXHAUSTED"

    def test_detail_in_message(self) -> None:
        err = BudgetExhaustedError("tokens exceeded: 5200 > 5000")
        assert "tokens exceeded" in str(err)
