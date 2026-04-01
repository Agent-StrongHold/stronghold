"""Outcome tracker — closed-loop feedback for model selection.

Tracks rolling-window statistics per model and provider so the router
can incorporate real-world performance data into scoring decisions:

- Latency P50/P99 per model
- Tool success rate per model per task_type
- Provider reliability (error rate)

All windows default to the last 100 observations per metric.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

_DEFAULT_WINDOW_SIZE = 100


@dataclass(frozen=True)
class ModelStats:
    """Aggregated outcome statistics for a single model."""

    p50_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    tool_success_rates: dict[str, float] = field(default_factory=dict)
    request_count: int = 0


class OutcomeTracker:
    """Tracks rolling outcome metrics for models and providers.

    Thread-safety note: this implementation is not thread-safe.
    For concurrent access, wrap calls with an external lock or
    use a thread-safe subclass.
    """

    def __init__(self, window_size: int = _DEFAULT_WINDOW_SIZE) -> None:
        self._window_size = window_size
        # model_id → deque of latencies
        self._latencies: dict[str, deque[float]] = {}
        # model_id → task_type → deque of bools (True = success)
        self._tool_outcomes: dict[str, dict[str, deque[bool]]] = {}
        # provider → deque of bools (True = success)
        self._provider_outcomes: dict[str, deque[bool]] = {}

    def record_latency(self, model_id: str, latency_ms: float) -> None:
        """Record a request latency observation for a model."""
        if model_id not in self._latencies:
            self._latencies[model_id] = deque(maxlen=self._window_size)
        self._latencies[model_id].append(latency_ms)

    def record_tool_outcome(
        self,
        model_id: str,
        task_type: str,
        *,
        success: bool,
    ) -> None:
        """Record a tool call outcome for a model and task type."""
        if model_id not in self._tool_outcomes:
            self._tool_outcomes[model_id] = {}
        by_task = self._tool_outcomes[model_id]
        if task_type not in by_task:
            by_task[task_type] = deque(maxlen=self._window_size)
        by_task[task_type].append(success)

    def record_error(
        self,
        provider: str,
        *,
        is_error: bool = True,
    ) -> None:
        """Record a provider request outcome (success or error).

        Args:
            provider: Provider identifier (e.g. "openai", "anthropic").
            is_error: True if the request failed, False if it succeeded.
        """
        if provider not in self._provider_outcomes:
            self._provider_outcomes[provider] = deque(maxlen=self._window_size)
        self._provider_outcomes[provider].append(not is_error)

    def get_model_stats(self, model_id: str) -> ModelStats:
        """Return aggregated stats for a model. Returns defaults for unknown models."""
        latencies = self._latencies.get(model_id)
        if not latencies:
            # Cold start — no data
            tool_rates = self._compute_tool_rates(model_id)
            return ModelStats(
                p50_latency_ms=0.0,
                p99_latency_ms=0.0,
                tool_success_rates=tool_rates,
                request_count=0,
            )

        sorted_lats = sorted(latencies)
        n = len(sorted_lats)
        p50 = self._percentile(sorted_lats, n, 50)
        p99 = self._percentile(sorted_lats, n, 99)
        tool_rates = self._compute_tool_rates(model_id)

        return ModelStats(
            p50_latency_ms=p50,
            p99_latency_ms=p99,
            tool_success_rates=tool_rates,
            request_count=n,
        )

    def get_provider_reliability(self, provider: str) -> float:
        """Return success rate for a provider. Returns 1.0 for unknown providers."""
        outcomes = self._provider_outcomes.get(provider)
        if not outcomes:
            return 1.0
        return sum(1 for ok in outcomes if ok) / len(outcomes)

    def _compute_tool_rates(self, model_id: str) -> dict[str, float]:
        """Compute success rates for each task_type a model has outcomes for."""
        by_task = self._tool_outcomes.get(model_id)
        if not by_task:
            return {}
        rates: dict[str, float] = {}
        for task_type, outcomes in by_task.items():
            if outcomes:
                rates[task_type] = sum(1 for ok in outcomes if ok) / len(outcomes)
        return rates

    @staticmethod
    def _percentile(sorted_values: list[float], n: int, pct: int) -> float:
        """Compute a percentile using nearest-rank method."""
        if n == 1:
            return sorted_values[0]
        rank = (pct / 100.0) * (n - 1)
        lower = int(math.floor(rank))
        upper = min(lower + 1, n - 1)
        frac = rank - lower
        return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])
