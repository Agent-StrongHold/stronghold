"""Per-user intelligent rate limiter with burst allowance.

Sliding window (1 minute) per user_id. The burst multiplier allows a
short spike above the base RPM: e.g. default_rpm=60, burst_multiplier=1.5
means the first 90 requests in a window are allowed, then strict 60 RPM.

For distributed deployments, replace with Redis-backed implementation
using the same interface.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

# Evict keys not seen in this many seconds
_KEY_EVICTION_AGE_S = 300  # 5 minutes
# Run eviction every N check() calls
_EVICTION_INTERVAL = 1000


class UserRateLimiter:
    """Per-user rate limiter with burst allowance."""

    def __init__(
        self,
        default_rpm: int = 60,
        burst_multiplier: float = 1.5,
    ) -> None:
        self._default_rpm = default_rpm
        self._burst_multiplier = burst_multiplier
        self._window_seconds = 60.0
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._check_count = 0

    async def check(self, user_id: str, org_id: str) -> bool:
        """Return True if the request is allowed, False if rate limited.

        Args:
            user_id: Unique identifier for the user.
            org_id: Organisation identifier (reserved for per-org overrides).

        Returns:
            True when the user is within their rate limit.
        """
        now = time.monotonic()
        window = self._windows[user_id]
        self._prune(window, now)

        burst_cap = int(self._default_rpm * self._burst_multiplier)

        # Periodic eviction of stale keys
        self._check_count += 1
        if self._check_count >= _EVICTION_INTERVAL:
            self._evict_stale_keys(now)

        return len(window) < burst_cap

    async def record(self, user_id: str) -> None:
        """Record a request timestamp for the user."""
        self._windows[user_id].append(time.monotonic())

    def get_remaining(self, user_id: str) -> int:
        """Return remaining requests allowed in the current window."""
        now = time.monotonic()
        window = self._windows[user_id]
        self._prune(window, now)
        burst_cap = int(self._default_rpm * self._burst_multiplier)
        return max(burst_cap - len(window), 0)

    def get_reset_time(self, user_id: str) -> float:
        """Return seconds until the oldest entry in the window expires."""
        now = time.monotonic()
        window = self._windows[user_id]
        self._prune(window, now)
        if not window:
            return self._window_seconds
        oldest = window[0]
        return max(self._window_seconds - (now - oldest), 0.0)

    # ── internal helpers ────────────────────────────────────────────

    def _prune(self, window: deque[float], now: float) -> None:
        """Remove timestamps older than the sliding window."""
        cutoff = now - self._window_seconds
        while window and window[0] < cutoff:
            window.popleft()

    def _evict_stale_keys(self, now: float) -> None:
        """Remove user keys whose most recent entry is older than eviction age."""
        self._check_count = 0
        eviction_cutoff = now - _KEY_EVICTION_AGE_S
        stale = [k for k, v in self._windows.items() if not v or v[-1] < eviction_cutoff]
        for k in stale:
            del self._windows[k]
