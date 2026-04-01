"""Real-time health monitoring for providers and models.

Uses deque-based rolling windows for bounded memory usage.
No external dependencies — pure Python data structures.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class _ProviderRecord:
    """Single provider call record."""

    latency_ms: float
    success: bool
    timestamp: float


@dataclass
class _ModelRecord:
    """Single model call record."""

    latency_ms: float
    success: bool
    tool_success: bool | None
    timestamp: float


@dataclass
class _ProviderState:
    """Rolling window of provider call records."""

    records: deque[_ProviderRecord]
    last_error_at: float | None = None


@dataclass
class _ModelState:
    """Rolling window of model call records."""

    provider: str
    records: deque[_ModelRecord]


class HealthMonitor:
    """Track provider and model health using deque-based rolling windows.

    Thread-safe for single-writer scenarios (typical async event loop).
    For multi-process deployments, use Redis-backed implementation instead.

    Args:
        window_size: Maximum number of records to keep per provider/model.
        unhealthy_error_rate: Error rate threshold above which a provider
            is considered unhealthy. Default 0.5 (50%).
    """

    def __init__(
        self,
        window_size: int = 1000,
        unhealthy_error_rate: float = 0.5,
    ) -> None:
        self._window_size = window_size
        self._unhealthy_error_rate = unhealthy_error_rate
        self._providers: dict[str, _ProviderState] = {}
        self._models: dict[str, _ModelState] = {}

    def record_provider_call(
        self,
        provider: str,
        latency_ms: float,
        success: bool,
    ) -> None:
        """Record a single provider API call result.

        Args:
            provider: Provider name (e.g. "openai", "anthropic").
            latency_ms: Call latency in milliseconds.
            success: Whether the call succeeded.
        """
        if provider not in self._providers:
            self._providers[provider] = _ProviderState(
                records=deque(maxlen=self._window_size),
            )

        state = self._providers[provider]
        record = _ProviderRecord(
            latency_ms=latency_ms,
            success=success,
            timestamp=time.time(),
        )
        state.records.append(record)

        if not success:
            state.last_error_at = record.timestamp

    def record_model_call(
        self,
        model: str,
        provider: str,
        latency_ms: float,
        success: bool,
        *,
        tool_success: bool | None = None,
    ) -> None:
        """Record a single model call result.

        Args:
            model: Model name (e.g. "gpt-4o", "claude-3").
            provider: Provider name.
            latency_ms: Call latency in milliseconds.
            success: Whether the call succeeded.
            tool_success: Whether tool use succeeded (None if no tools).
        """
        if model not in self._models:
            self._models[model] = _ModelState(
                provider=provider,
                records=deque(maxlen=self._window_size),
            )

        state = self._models[model]
        record = _ModelRecord(
            latency_ms=latency_ms,
            success=success,
            tool_success=tool_success,
            timestamp=time.time(),
        )
        state.records.append(record)

    def get_provider_health(self) -> list[dict[str, Any]]:
        """Return per-provider health status.

        Returns a list of dicts with keys:
            name, is_healthy, error_rate, avg_latency_ms, last_error_at, request_count
        """
        result: list[dict[str, Any]] = []
        for name, state in sorted(self._providers.items()):
            records = state.records
            if not records:
                continue

            total = len(records)
            errors = sum(1 for r in records if not r.success)
            error_rate = errors / total
            avg_latency = sum(r.latency_ms for r in records) / total

            result.append(
                {
                    "name": name,
                    "is_healthy": error_rate <= self._unhealthy_error_rate,
                    "error_rate": error_rate,
                    "avg_latency_ms": avg_latency,
                    "last_error_at": state.last_error_at,
                    "request_count": total,
                }
            )
        return result

    def get_model_health(self) -> list[dict[str, Any]]:
        """Return per-model health status.

        Returns a list of dicts with keys:
            name, provider, avg_latency_ms, tool_success_rate, request_count
        """
        result: list[dict[str, Any]] = []
        for name, state in sorted(self._models.items()):
            records = state.records
            if not records:
                continue

            total = len(records)
            avg_latency = sum(r.latency_ms for r in records) / total

            # tool_success_rate: only count calls where tool_success is not None
            tool_calls = [r for r in records if r.tool_success is not None]
            if tool_calls:
                tool_success_rate = sum(1 for r in tool_calls if r.tool_success) / len(tool_calls)
            else:
                tool_success_rate = 0.0

            result.append(
                {
                    "name": name,
                    "provider": state.provider,
                    "avg_latency_ms": avg_latency,
                    "tool_success_rate": tool_success_rate,
                    "request_count": total,
                }
            )
        return result
