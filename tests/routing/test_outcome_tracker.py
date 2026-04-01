"""Tests for outcome tracker — closed-loop model selection feedback.

Covers: latency tracking (P50/P99), tool success rate per model per task_type,
provider reliability (error rate), cold start defaults, and rolling window eviction.
"""

from __future__ import annotations

from stronghold.router.outcome_tracker import OutcomeTracker


class TestLatencyRecording:
    def test_record_single_latency(self) -> None:
        tracker = OutcomeTracker()
        tracker.record_latency("gpt-4o", 150.0)
        stats = tracker.get_model_stats("gpt-4o")
        assert stats.p50_latency_ms == 150.0
        assert stats.p99_latency_ms == 150.0

    def test_record_multiple_latencies(self) -> None:
        tracker = OutcomeTracker()
        for ms in [100.0, 200.0, 300.0]:
            tracker.record_latency("gpt-4o", ms)
        stats = tracker.get_model_stats("gpt-4o")
        assert stats.p50_latency_ms == 200.0

    def test_latencies_per_model_are_independent(self) -> None:
        tracker = OutcomeTracker()
        tracker.record_latency("gpt-4o", 100.0)
        tracker.record_latency("claude-sonnet", 500.0)
        gpt_stats = tracker.get_model_stats("gpt-4o")
        claude_stats = tracker.get_model_stats("claude-sonnet")
        assert gpt_stats.p50_latency_ms == 100.0
        assert claude_stats.p50_latency_ms == 500.0


class TestP50P99Calculation:
    def test_p50_is_median(self) -> None:
        tracker = OutcomeTracker()
        # 10 values: 10, 20, ... 100
        for i in range(1, 11):
            tracker.record_latency("m", float(i * 10))
        stats = tracker.get_model_stats("m")
        # Median of [10..100] with 10 values: between 50 and 60
        assert 50.0 <= stats.p50_latency_ms <= 60.0

    def test_p99_captures_tail(self) -> None:
        tracker = OutcomeTracker()
        # 99 fast requests + 1 slow outlier
        for _ in range(99):
            tracker.record_latency("m", 50.0)
        tracker.record_latency("m", 5000.0)
        stats = tracker.get_model_stats("m")
        # P99 should be at or near the outlier
        assert stats.p99_latency_ms >= 50.0
        # P50 should be the fast value
        assert stats.p50_latency_ms == 50.0

    def test_p99_with_two_values(self) -> None:
        tracker = OutcomeTracker()
        tracker.record_latency("m", 10.0)
        tracker.record_latency("m", 1000.0)
        stats = tracker.get_model_stats("m")
        # With 2 values and linear interpolation, P99 is near the max
        assert stats.p99_latency_ms >= 980.0


class TestToolSuccessRate:
    def test_success_rate_all_successes(self) -> None:
        tracker = OutcomeTracker()
        for _ in range(10):
            tracker.record_tool_outcome("gpt-4o", "code", success=True)
        stats = tracker.get_model_stats("gpt-4o")
        assert stats.tool_success_rates["code"] == 1.0

    def test_success_rate_all_failures(self) -> None:
        tracker = OutcomeTracker()
        for _ in range(5):
            tracker.record_tool_outcome("gpt-4o", "code", success=False)
        stats = tracker.get_model_stats("gpt-4o")
        assert stats.tool_success_rates["code"] == 0.0

    def test_success_rate_mixed(self) -> None:
        tracker = OutcomeTracker()
        for _ in range(7):
            tracker.record_tool_outcome("gpt-4o", "code", success=True)
        for _ in range(3):
            tracker.record_tool_outcome("gpt-4o", "code", success=False)
        stats = tracker.get_model_stats("gpt-4o")
        assert abs(stats.tool_success_rates["code"] - 0.7) < 0.01

    def test_success_rate_per_task_type(self) -> None:
        tracker = OutcomeTracker()
        tracker.record_tool_outcome("gpt-4o", "code", success=True)
        tracker.record_tool_outcome("gpt-4o", "chat", success=False)
        stats = tracker.get_model_stats("gpt-4o")
        assert stats.tool_success_rates["code"] == 1.0
        assert stats.tool_success_rates["chat"] == 0.0


class TestProviderReliability:
    def test_no_errors_full_reliability(self) -> None:
        tracker = OutcomeTracker()
        # Record some latency so the provider has data
        tracker.record_latency("gpt-4o", 100.0)
        reliability = tracker.get_provider_reliability("openai")
        # No errors recorded — default 1.0
        assert reliability == 1.0

    def test_errors_reduce_reliability(self) -> None:
        tracker = OutcomeTracker()
        for _ in range(10):
            tracker.record_error("openai")
        # 10 errors, 0 successes → 0.0 reliability
        reliability = tracker.get_provider_reliability("openai")
        assert reliability == 0.0

    def test_mixed_errors_and_successes(self) -> None:
        tracker = OutcomeTracker()
        for _ in range(8):
            tracker.record_error("openai", is_error=False)  # success
        for _ in range(2):
            tracker.record_error("openai", is_error=True)
        reliability = tracker.get_provider_reliability("openai")
        assert abs(reliability - 0.8) < 0.01


class TestColdStart:
    def test_unknown_model_returns_defaults(self) -> None:
        tracker = OutcomeTracker()
        stats = tracker.get_model_stats("never-seen-model")
        assert stats.p50_latency_ms == 0.0
        assert stats.p99_latency_ms == 0.0
        assert stats.tool_success_rates == {}
        assert stats.request_count == 0

    def test_unknown_provider_returns_full_reliability(self) -> None:
        tracker = OutcomeTracker()
        reliability = tracker.get_provider_reliability("unknown-provider")
        assert reliability == 1.0


class TestRollingWindowEviction:
    def test_latency_window_caps_at_max(self) -> None:
        tracker = OutcomeTracker(window_size=10)
        # Record 15 values — first 5 should be evicted
        for i in range(15):
            tracker.record_latency("m", float(i * 10))
        stats = tracker.get_model_stats("m")
        # Only last 10 values (50..140) should remain
        # P50 of [50, 60, 70, 80, 90, 100, 110, 120, 130, 140]
        assert 90.0 <= stats.p50_latency_ms <= 100.0

    def test_tool_outcome_window_caps_at_max(self) -> None:
        tracker = OutcomeTracker(window_size=10)
        # Record 10 successes, then 10 failures — only failures should remain
        for _ in range(10):
            tracker.record_tool_outcome("m", "code", success=True)
        for _ in range(10):
            tracker.record_tool_outcome("m", "code", success=False)
        stats = tracker.get_model_stats("m")
        assert stats.tool_success_rates["code"] == 0.0

    def test_provider_reliability_window_caps_at_max(self) -> None:
        tracker = OutcomeTracker(window_size=10)
        # 10 successes, then 10 errors — only errors remain
        for _ in range(10):
            tracker.record_error("prov", is_error=False)
        for _ in range(10):
            tracker.record_error("prov", is_error=True)
        reliability = tracker.get_provider_reliability("prov")
        assert reliability == 0.0


class TestRequestCount:
    def test_request_count_tracks_latencies(self) -> None:
        tracker = OutcomeTracker()
        for _ in range(5):
            tracker.record_latency("m", 100.0)
        stats = tracker.get_model_stats("m")
        assert stats.request_count == 5

    def test_request_count_respects_window(self) -> None:
        tracker = OutcomeTracker(window_size=10)
        for _ in range(25):
            tracker.record_latency("m", 100.0)
        stats = tracker.get_model_stats("m")
        assert stats.request_count == 10
