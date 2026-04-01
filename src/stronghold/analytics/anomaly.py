"""Statistical anomaly detection over operational signals."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class AnomalyAlert:
    """An alert raised when a signal value exceeds its statistical threshold."""

    signal_name: str
    current_value: float
    mean: float
    stddev: float
    threshold: float  # mean + N*stddev
    severity: str  # "warning" (2-sigma) or "critical" (3-sigma)
    timestamp: float = 0.0


class RollingStats:
    """Track rolling mean and stddev for a signal over a time window."""

    def __init__(self, window_size: int = 60) -> None:
        self._values: deque[tuple[float, float]] = deque()  # (timestamp, value)
        self._window = window_size

    def record(self, value: float, timestamp: float | None = None) -> None:
        """Record a new value at the given timestamp."""
        ts = timestamp if timestamp is not None else time.time()
        self._values.append((ts, value))
        self._prune(ts)

    @property
    def mean(self) -> float:
        """Return the arithmetic mean of values in the window."""
        if not self._values:
            return 0.0
        total = sum(v for _, v in self._values)
        return total / len(self._values)

    @property
    def stddev(self) -> float:
        """Return the population standard deviation of values in the window."""
        n = len(self._values)
        if n < 2:
            return 0.0
        m = self.mean
        variance = sum((v - m) ** 2 for _, v in self._values) / n
        return math.sqrt(variance)

    @property
    def count(self) -> int:
        """Return the number of values currently in the window."""
        return len(self._values)

    def _prune(self, now: float) -> None:
        """Remove values outside the window."""
        cutoff = now - self._window
        while self._values and self._values[0][0] < cutoff:
            self._values.popleft()


class AnomalyDetector:
    """Monitor multiple signals and detect anomalies using sigma thresholds."""

    def __init__(
        self,
        warning_sigma: float = 2.0,
        critical_sigma: float = 3.0,
        min_samples: int = 10,
    ) -> None:
        self._signals: dict[str, RollingStats] = {}
        self._warning_sigma = warning_sigma
        self._critical_sigma = critical_sigma
        self._min_samples = min_samples
        self._alerts: list[AnomalyAlert] = []

    def record(self, signal_name: str, value: float) -> AnomalyAlert | None:
        """Record a value and check for anomaly. Returns alert if detected."""
        if signal_name not in self._signals:
            self._signals[signal_name] = RollingStats()

        stats = self._signals[signal_name]

        # Check before recording (compare against existing baseline)
        alert: AnomalyAlert | None = None
        if stats.count >= self._min_samples:
            m = stats.mean
            s = stats.stddev
            now = time.time()

            if s > 0:
                critical_threshold = m + self._critical_sigma * s
                warning_threshold = m + self._warning_sigma * s
                if value >= critical_threshold:
                    alert = AnomalyAlert(
                        signal_name=signal_name,
                        current_value=value,
                        mean=m,
                        stddev=s,
                        threshold=critical_threshold,
                        severity="critical",
                        timestamp=now,
                    )
                    self._alerts.append(alert)
                elif value >= warning_threshold:
                    alert = AnomalyAlert(
                        signal_name=signal_name,
                        current_value=value,
                        mean=m,
                        stddev=s,
                        threshold=warning_threshold,
                        severity="warning",
                        timestamp=now,
                    )
                    self._alerts.append(alert)
            elif value != m:
                # Zero stddev means perfectly stable signal; any deviation
                # is infinitely many sigmas away, so treat as critical.
                alert = AnomalyAlert(
                    signal_name=signal_name,
                    current_value=value,
                    mean=m,
                    stddev=0.0,
                    threshold=m,
                    severity="critical",
                    timestamp=now,
                )
                self._alerts.append(alert)

        stats.record(value)
        return alert

    def get_alerts(self, since: float = 0.0) -> list[AnomalyAlert]:
        """Return alerts, optionally filtered to those after a given timestamp."""
        return [a for a in self._alerts if a.timestamp >= since]

    def get_signal_stats(self, signal_name: str) -> dict[str, Any]:
        """Return current statistics for a signal."""
        if signal_name not in self._signals:
            return {"mean": 0.0, "stddev": 0.0, "count": 0}
        stats = self._signals[signal_name]
        return {
            "mean": stats.mean,
            "stddev": stats.stddev,
            "count": stats.count,
        }

    def list_signals(self) -> list[str]:
        """Return the names of all registered signals."""
        return list(self._signals.keys())
