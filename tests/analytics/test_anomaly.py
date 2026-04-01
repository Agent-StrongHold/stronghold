"""Tests for statistical anomaly detection over operational signals."""
from __future__ import annotations

import math
import time

from stronghold.analytics.anomaly import AnomalyAlert, AnomalyDetector, RollingStats


class TestRollingStatsMean:
    """Mean calculation on rolling window."""

    def test_mean_single_value(self) -> None:
        stats = RollingStats(window_size=60)
        stats.record(10.0, timestamp=1.0)
        assert stats.mean == 10.0

    def test_mean_multiple_values(self) -> None:
        stats = RollingStats(window_size=60)
        stats.record(10.0, timestamp=1.0)
        stats.record(20.0, timestamp=2.0)
        stats.record(30.0, timestamp=3.0)
        assert stats.mean == 20.0

    def test_mean_empty_is_zero(self) -> None:
        stats = RollingStats(window_size=60)
        assert stats.mean == 0.0


class TestRollingStatsStddev:
    """Standard deviation calculation."""

    def test_stddev_single_value_is_zero(self) -> None:
        stats = RollingStats(window_size=60)
        stats.record(10.0, timestamp=1.0)
        assert stats.stddev == 0.0

    def test_stddev_identical_values_is_zero(self) -> None:
        stats = RollingStats(window_size=60)
        for i in range(5):
            stats.record(5.0, timestamp=float(i))
        assert stats.stddev == 0.0

    def test_stddev_known_values(self) -> None:
        stats = RollingStats(window_size=60)
        values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        for i, v in enumerate(values):
            stats.record(v, timestamp=float(i))
        # Population stddev of [2,4,4,4,5,5,7,9] = 2.0
        assert abs(stats.stddev - 2.0) < 0.01

    def test_stddev_empty_is_zero(self) -> None:
        stats = RollingStats(window_size=60)
        assert stats.stddev == 0.0


class TestRollingStatsCount:
    """Count of values in window."""

    def test_count_empty(self) -> None:
        stats = RollingStats(window_size=60)
        assert stats.count == 0

    def test_count_after_records(self) -> None:
        stats = RollingStats(window_size=60)
        stats.record(1.0, timestamp=1.0)
        stats.record(2.0, timestamp=2.0)
        assert stats.count == 2


class TestRollingStatsWindowPruning:
    """Values outside the window are pruned."""

    def test_old_values_pruned(self) -> None:
        stats = RollingStats(window_size=10)
        stats.record(100.0, timestamp=1.0)
        stats.record(100.0, timestamp=2.0)
        # Record at timestamp 20 — window is [10, 20], so ts=1 and ts=2 are pruned
        stats.record(5.0, timestamp=20.0)
        assert stats.count == 1
        assert stats.mean == 5.0

    def test_window_boundary_inclusive(self) -> None:
        stats = RollingStats(window_size=10)
        stats.record(10.0, timestamp=5.0)
        # At timestamp 15, window is [5, 15] — ts=5 should still be in
        stats.record(20.0, timestamp=15.0)
        assert stats.count == 2
        assert stats.mean == 15.0


class TestAnomalyDetectorNormalValues:
    """Normal values should not produce alerts."""

    def test_no_alert_for_stable_values(self) -> None:
        detector = AnomalyDetector(min_samples=5)
        # Record 20 stable values
        for i in range(20):
            alert = detector.record("requests", 100.0)
        assert alert is None

    def test_no_alert_with_minor_variation(self) -> None:
        detector = AnomalyDetector(min_samples=5)
        values = [100.0, 101.0, 99.0, 100.5, 99.5, 100.0, 101.0, 99.0, 100.0, 100.0]
        alert = None
        for v in values:
            alert = detector.record("requests", v)
        assert alert is None


class TestAnomalyDetectorMinSamples:
    """No alerts until min_samples is reached."""

    def test_no_alert_below_min_samples(self) -> None:
        detector = AnomalyDetector(min_samples=10)
        # Even a huge spike should not alert if we haven't hit min_samples
        for i in range(9):
            detector.record("requests", 100.0)
        alert = detector.record("requests", 99999.0)
        assert alert is None

    def test_alert_possible_after_min_samples(self) -> None:
        detector = AnomalyDetector(min_samples=5, warning_sigma=2.0)
        for i in range(10):
            detector.record("requests", 100.0)
        # Mean=100, stddev ~0, so a value of 200 should trigger
        alert = detector.record("requests", 200.0)
        assert alert is not None


class TestAnomalyDetectorWarning:
    """Warning alerts at 2 sigma."""

    def test_warning_on_spike(self) -> None:
        detector = AnomalyDetector(warning_sigma=2.0, critical_sigma=3.0, min_samples=5)
        # Build baseline
        for i in range(20):
            detector.record("error_rate", 10.0 + (i % 3))
        # Record a value well above 2 sigma but check severity
        stats = detector._signals["error_rate"]
        spike = stats.mean + 2.5 * stats.stddev
        alert = detector.record("error_rate", spike)
        assert alert is not None
        assert alert.severity == "warning"
        assert alert.signal_name == "error_rate"


class TestAnomalyDetectorCritical:
    """Critical alerts at 3 sigma."""

    def test_critical_on_large_spike(self) -> None:
        detector = AnomalyDetector(warning_sigma=2.0, critical_sigma=3.0, min_samples=5)
        for i in range(20):
            detector.record("latency", 50.0 + (i % 5))
        stats = detector._signals["latency"]
        spike = stats.mean + 4.0 * stats.stddev
        alert = detector.record("latency", spike)
        assert alert is not None
        assert alert.severity == "critical"


class TestAnomalyDetectorMultipleSignals:
    """Multiple signals are tracked independently."""

    def test_independent_signals(self) -> None:
        detector = AnomalyDetector(min_samples=5)
        # Build baseline for signal A
        for i in range(10):
            detector.record("signal_a", 100.0)
        # Build baseline for signal B with different range
        for i in range(10):
            detector.record("signal_b", 5.0)
        # Spike on signal_a should not affect signal_b
        alert_a = detector.record("signal_a", 999.0)
        assert alert_a is not None
        assert alert_a.signal_name == "signal_a"
        # signal_b should still be fine
        alert_b = detector.record("signal_b", 5.0)
        assert alert_b is None


class TestAnomalyDetectorGetAlerts:
    """get_alerts returns historical alerts filtered by timestamp."""

    def test_get_alerts_returns_all(self) -> None:
        detector = AnomalyDetector(min_samples=5)
        for i in range(10):
            detector.record("sig", 100.0)
        detector.record("sig", 999.0)
        alerts = detector.get_alerts()
        assert len(alerts) >= 1

    def test_get_alerts_filters_by_since(self) -> None:
        detector = AnomalyDetector(min_samples=5)
        for i in range(10):
            detector.record("sig", 100.0)
        detector.record("sig", 999.0)
        # Filter with a future timestamp should return nothing
        alerts = detector.get_alerts(since=time.time() + 1000)
        assert len(alerts) == 0


class TestAnomalyDetectorListSignals:
    """list_signals returns registered signal names."""

    def test_list_signals_empty(self) -> None:
        detector = AnomalyDetector()
        assert detector.list_signals() == []

    def test_list_signals_after_recording(self) -> None:
        detector = AnomalyDetector()
        detector.record("requests", 1.0)
        detector.record("errors", 2.0)
        signals = detector.list_signals()
        assert sorted(signals) == ["errors", "requests"]


class TestAnomalyDetectorGetSignalStats:
    """get_signal_stats returns current stats for a signal."""

    def test_stats_for_existing_signal(self) -> None:
        detector = AnomalyDetector()
        for i in range(5):
            detector.record("cpu", 50.0 + i)
        stats = detector.get_signal_stats("cpu")
        assert "mean" in stats
        assert "stddev" in stats
        assert "count" in stats
        assert stats["count"] == 5

    def test_stats_for_unknown_signal(self) -> None:
        detector = AnomalyDetector()
        stats = detector.get_signal_stats("nonexistent")
        assert stats["count"] == 0


class TestAnomalyAlertDataclass:
    """AnomalyAlert dataclass construction."""

    def test_alert_fields(self) -> None:
        alert = AnomalyAlert(
            signal_name="requests",
            current_value=500.0,
            mean=100.0,
            stddev=50.0,
            threshold=200.0,
            severity="warning",
            timestamp=123.456,
        )
        assert alert.signal_name == "requests"
        assert alert.current_value == 500.0
        assert alert.mean == 100.0
        assert alert.stddev == 50.0
        assert alert.threshold == 200.0
        assert alert.severity == "warning"
        assert alert.timestamp == 123.456

    def test_alert_default_timestamp(self) -> None:
        alert = AnomalyAlert(
            signal_name="x",
            current_value=0.0,
            mean=0.0,
            stddev=0.0,
            threshold=0.0,
            severity="warning",
        )
        assert alert.timestamp == 0.0
