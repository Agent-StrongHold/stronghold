"""Nested-loop workflow tracking for Builders 2.0.

Implements:
- MasonTestTracker: sophisticated test tracking with high water mark and counter reset
- OuterLoopTracker: outer loop failure counting with max 5
- ModelEscalator: model selection based on retry count
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MasonTestTracker:
    """Sophisticated test tracking for Mason's inner build loop.

    Implements high water mark and counter reset logic:
    - Tracks the highest number of passing tests ever achieved
    - Increments counter when current run doesn't beat high water mark
    - Resets counter to 0 when current run beats high water mark
    - Triggers failure after 10 consecutive non-improving runs
    """

    high_water_mark: int = 0
    stall_counter: int = 0
    has_failed: bool = False

    def record_test_result(self, passing_count: int) -> None:
        """Record test results and update tracking state."""
        if passing_count > self.high_water_mark:
            self.high_water_mark = passing_count
            self.stall_counter = 0
        else:
            self.stall_counter += 1

        if self.stall_counter >= 10 and not self.has_failed:
            self.has_failed = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "high_water_mark": self.high_water_mark,
            "stall_counter": self.stall_counter,
            "has_failed": self.has_failed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MasonTestTracker:
        return cls(
            high_water_mark=data.get("high_water_mark", 0),
            stall_counter=data.get("stall_counter", 0),
            has_failed=data.get("has_failed", False),
        )


@dataclass
class OuterLoopTracker:
    """Outer loop retry tracking with max 5 failures before admin signaling."""

    failure_count: int = 0
    max_failures: int = 5

    def record_failure(self) -> None:
        """Record a failed outer loop attempt."""
        self.failure_count += 1

    def record_success(self) -> None:
        """Reset failure count on successful completion."""
        self.failure_count = 0

    @property
    def should_signal_admin(self) -> bool:
        """Check if admin should be signaled due to max failures."""
        return self.failure_count >= self.max_failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "failure_count": self.failure_count,
            "max_failures": self.max_failures,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OuterLoopTracker:
        return cls(
            failure_count=data.get("failure_count", 0),
            max_failures=data.get("max_failures", 5),
        )


@dataclass
class ModelEscalator:
    """Model selection based on retry count for outer loop escalation."""

    model_priority: list[str] = field(
        default_factory=lambda: [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "mistral-large",
            "claude-3-opus",
        ]
    )

    def select_model(self, retry_count: int) -> str | None:
        """Select model based on retry count.

        Escalates to more powerful models with each retry.
        Caps at the most powerful model in the priority list.
        """
        if not self.model_priority:
            return None
        index = min(retry_count, len(self.model_priority) - 1)
        return self.model_priority[index]
