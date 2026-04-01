"""Execution modes, token budget tracking, and execution context.

Three execution modes control how much effort and oversight a request gets:
- BEST_EFFORT: sanitize + Warden scan. Block if malicious, pass through otherwise.
- PERSISTENT: + request sufficiency check. Returns clarifying questions if insufficient.
- SUPERVISED: always returns clarifying questions (human-in-the-loop).

TokenBudget tracks token consumption and prevents cost overruns.
ExecutionContext bundles mode, budget, decision points, and status callback.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from stronghold.types.errors import StrongholdError

# Type alias for async status callbacks: async def callback(msg: str) -> None
StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


class ExecutionMode(StrEnum):
    """How much effort and oversight to apply to a request."""

    BEST_EFFORT = "best_effort"
    PERSISTENT = "persistent"
    SUPERVISED = "supervised"


class BudgetExhaustedError(StrongholdError):
    """Token budget has been exceeded."""

    code = "BUDGET_EXHAUSTED"


@dataclass
class TokenBudget:
    """Tracks token usage against a maximum budget.

    Attributes:
        max_tokens: The hard ceiling for total token consumption.
        used_tokens: Tokens consumed so far.
    """

    max_tokens: int
    used_tokens: int = 0

    def can_afford(self, estimated: int) -> bool:
        """Check whether the estimated token cost fits within the remaining budget."""
        return self.used_tokens + estimated <= self.max_tokens

    def record(self, actual: int) -> None:
        """Record actual token usage. Raises BudgetExhaustedError if it exceeds max."""
        new_total = self.used_tokens + actual
        if new_total > self.max_tokens:
            raise BudgetExhaustedError(
                f"Token budget exceeded: {new_total} would exceed "
                f"max of {self.max_tokens} (used={self.used_tokens}, recording={actual})"
            )
        self.used_tokens = new_total

    @property
    def remaining(self) -> int:
        """Tokens still available."""
        return max(self.max_tokens - self.used_tokens, 0)

    @property
    def usage_pct(self) -> float:
        """Fraction of budget consumed (0.0 to 1.0+)."""
        if self.max_tokens == 0:
            return 1.0
        return self.used_tokens / self.max_tokens


@dataclass
class ExecutionContext:
    """Runtime context for a single execution: mode, budget, decisions, callback.

    Attributes:
        mode: The execution mode controlling effort/oversight level.
        budget: Optional token budget for cost control.
        decision_points: In SUPERVISED mode, records questions for human review.
        status_callback: Optional async callback for progress updates.
    """

    mode: ExecutionMode = ExecutionMode.BEST_EFFORT
    budget: TokenBudget | None = None
    decision_points: list[str] = field(default_factory=list)
    status_callback: StatusCallback | None = None

    def record_decision(self, description: str) -> None:
        """Record a decision point for supervised review."""
        self.decision_points.append(description)
