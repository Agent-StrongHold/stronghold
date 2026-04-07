"""Tests for HealthMonitor — deque-based rolling-window health tracking.

TDD: tests written first, then implementation.
"""

from __future__ import annotations

import time

from stronghold.monitoring.health import HealthMonitor


class TestRecordProviderCall:
    """record_provider_call stores latency/success data per provider."""

    def test_record_single_success(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_provider_call("openai", latency_ms=120.0, success=True)

        health = monitor.get_provider_health()
        assert len(health) == 1
        assert health[0]["name"] == "openai"
        assert health[0]["is_healthy"] is True
        assert health[0]["request_count"] == 1
        assert health[0]["error_rate"] == 0.0
        assert health[0]["avg_latency_ms"] == 120.0

    def test_record_single_failure(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_provider_call("anthropic", latency_ms=5000.0, success=False)

        health = monitor.get_provider_health()
        assert len(health) == 1
        assert health[0]["name"] == "anthropic"
        assert health[0]["error_rate"] == 1.0
        assert health[0]["last_error_at"] is not None

    def test_record_multiple_providers(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_provider_call("openai", latency_ms=100.0, success=True)
        monitor.record_provider_call("anthropic", latency_ms=200.0, success=True)

        health = monitor.get_provider_health()
        names = {h["name"] for h in health}
        assert names == {"openai", "anthropic"}

    def test_mixed_success_and_failure(self) -> None:
        monitor = HealthMonitor(window_size=100)
        # 3 successes, 1 failure = 25% error rate
        monitor.record_provider_call("openai", latency_ms=100.0, success=True)
        monitor.record_provider_call("openai", latency_ms=120.0, success=True)
        monitor.record_provider_call("openai", latency_ms=110.0, success=True)
        monitor.record_provider_call("openai", latency_ms=5000.0, success=False)

        health = monitor.get_provider_health()
        assert len(health) == 1
        p = health[0]
        assert p["request_count"] == 4
        assert p["error_rate"] == 0.25
        assert p["avg_latency_ms"] == (100.0 + 120.0 + 110.0 + 5000.0) / 4


class TestProviderHealthThreshold:
    """is_healthy should be False when error_rate exceeds threshold."""

    def test_healthy_below_threshold(self) -> None:
        monitor = HealthMonitor(window_size=100, unhealthy_error_rate=0.5)
        monitor.record_provider_call("openai", latency_ms=100.0, success=True)
        monitor.record_provider_call("openai", latency_ms=200.0, success=False)

        health = monitor.get_provider_health()
        # 50% error rate == threshold, still healthy (> not >=)
        assert health[0]["is_healthy"] is True

    def test_unhealthy_above_threshold(self) -> None:
        monitor = HealthMonitor(window_size=100, unhealthy_error_rate=0.5)
        monitor.record_provider_call("openai", latency_ms=100.0, success=False)
        monitor.record_provider_call("openai", latency_ms=200.0, success=False)
        monitor.record_provider_call("openai", latency_ms=150.0, success=True)

        health = monitor.get_provider_health()
        # 66% error rate > 50% threshold
        assert health[0]["is_healthy"] is False


class TestRecordModelCall:
    """record_model_call stores per-model latency and tool success data."""

    def test_record_model_latency(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_model_call(
            model="gpt-4o",
            provider="openai",
            latency_ms=250.0,
            success=True,
            tool_success=True,
        )

        health = monitor.get_model_health()
        assert len(health) == 1
        m = health[0]
        assert m["name"] == "gpt-4o"
        assert m["provider"] == "openai"
        assert m["avg_latency_ms"] == 250.0
        assert m["tool_success_rate"] == 1.0
        assert m["request_count"] == 1

    def test_model_tool_success_rate(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_model_call("gpt-4o", "openai", 200.0, True, tool_success=True)
        monitor.record_model_call("gpt-4o", "openai", 300.0, True, tool_success=False)
        monitor.record_model_call("gpt-4o", "openai", 250.0, True, tool_success=True)
        # Only count calls where tool_success is not None
        monitor.record_model_call("gpt-4o", "openai", 150.0, True, tool_success=None)

        health = monitor.get_model_health()
        m = health[0]
        assert m["request_count"] == 4
        # tool_success_rate only counts non-None: 2/3
        assert abs(m["tool_success_rate"] - 2.0 / 3.0) < 0.01

    def test_multiple_models(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_model_call("gpt-4o", "openai", 200.0, True, tool_success=True)
        monitor.record_model_call("claude-3", "anthropic", 180.0, True, tool_success=True)

        health = monitor.get_model_health()
        names = {m["name"] for m in health}
        assert names == {"gpt-4o", "claude-3"}


class TestRollingWindow:
    """Window evicts oldest entries when full."""

    def test_window_eviction(self) -> None:
        monitor = HealthMonitor(window_size=3)
        # Fill window: 3 successes
        monitor.record_provider_call("openai", latency_ms=100.0, success=True)
        monitor.record_provider_call("openai", latency_ms=200.0, success=True)
        monitor.record_provider_call("openai", latency_ms=300.0, success=True)
        # 4th call evicts the 100ms call
        monitor.record_provider_call("openai", latency_ms=400.0, success=False)

        health = monitor.get_provider_health()
        p = health[0]
        assert p["request_count"] == 3  # window_size=3
        assert p["avg_latency_ms"] == (200.0 + 300.0 + 400.0) / 3
        assert abs(p["error_rate"] - 1.0 / 3.0) < 0.01


class TestLastErrorAt:
    """last_error_at tracks the most recent failure timestamp."""

    def test_no_errors_returns_none(self) -> None:
        monitor = HealthMonitor(window_size=100)
        monitor.record_provider_call("openai", latency_ms=100.0, success=True)

        health = monitor.get_provider_health()
        assert health[0]["last_error_at"] is None

    def test_error_records_timestamp(self) -> None:
        monitor = HealthMonitor(window_size=100)
        before = time.time()
        monitor.record_provider_call("openai", latency_ms=5000.0, success=False)
        after = time.time()

        health = monitor.get_provider_health()
        ts = health[0]["last_error_at"]
        assert ts is not None
        assert before <= ts <= after


class TestEmptyState:
    """Health reports are empty when no data has been recorded."""

    def test_empty_provider_health(self) -> None:
        monitor = HealthMonitor(window_size=100)
        assert monitor.get_provider_health() == []

    def test_empty_model_health(self) -> None:
        monitor = HealthMonitor(window_size=100)
        assert monitor.get_model_health() == []
