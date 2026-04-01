"""Per-user rate limiter tests: sliding window, burst allowance, org isolation."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from stronghold.security.user_rate_limiter import UserRateLimiter


class TestUserRateLimiterBasic:
    """Core allow/deny behavior."""

    async def test_allows_under_limit(self) -> None:
        limiter = UserRateLimiter(default_rpm=10)
        for _ in range(10):
            allowed = await limiter.check("alice", "org-1")
            assert allowed
            await limiter.record("alice")

    async def test_blocks_after_limit_exhausted(self) -> None:
        limiter = UserRateLimiter(default_rpm=5, burst_multiplier=1.0)
        for _ in range(5):
            await limiter.record("alice")

        allowed = await limiter.check("alice", "org-1")
        assert not allowed

    async def test_different_users_independent(self) -> None:
        limiter = UserRateLimiter(default_rpm=3, burst_multiplier=1.0)
        for _ in range(3):
            await limiter.record("alice")

        # Alice blocked
        assert not await limiter.check("alice", "org-1")
        # Bob fine
        assert await limiter.check("bob", "org-1")


class TestBurstAllowance:
    """Burst multiplier allows initial spike above base RPM."""

    async def test_burst_allows_above_base_rpm(self) -> None:
        # default_rpm=10, burst_multiplier=1.5 => burst cap = 15
        limiter = UserRateLimiter(default_rpm=10, burst_multiplier=1.5)
        for _ in range(14):
            await limiter.record("alice")

        # 14 < 15 burst cap => still allowed
        allowed = await limiter.check("alice", "org-1")
        assert allowed

    async def test_burst_blocks_after_burst_cap(self) -> None:
        # default_rpm=10, burst_multiplier=1.5 => burst cap = 15
        limiter = UserRateLimiter(default_rpm=10, burst_multiplier=1.5)
        for _ in range(15):
            await limiter.record("alice")

        # 15 >= 15 burst cap => blocked
        allowed = await limiter.check("alice", "org-1")
        assert not allowed

    async def test_burst_multiplier_one_means_no_burst(self) -> None:
        limiter = UserRateLimiter(default_rpm=5, burst_multiplier=1.0)
        for _ in range(5):
            await limiter.record("alice")

        assert not await limiter.check("alice", "org-1")

    async def test_default_burst_multiplier_is_1_5(self) -> None:
        limiter = UserRateLimiter(default_rpm=10)
        assert limiter._burst_multiplier == 1.5  # noqa: SLF001


class TestSlidingWindow:
    """Window expiry resets counts."""

    async def test_window_expiry_resets_count(self) -> None:
        limiter = UserRateLimiter(default_rpm=3, burst_multiplier=1.0)

        now = time.monotonic()
        with patch("stronghold.security.user_rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = now
            for _ in range(3):
                await limiter.record("alice")

            # Blocked right now
            assert not await limiter.check("alice", "org-1")

            # Advance past the 60s window
            mock_time.monotonic.return_value = now + 61.0
            assert await limiter.check("alice", "org-1")

    async def test_partial_window_expiry(self) -> None:
        """Only old entries expire; recent ones remain."""
        limiter = UserRateLimiter(default_rpm=4, burst_multiplier=1.0)

        now = time.monotonic()
        with patch("stronghold.security.user_rate_limiter.time") as mock_time:
            # Record 2 requests at t=0
            mock_time.monotonic.return_value = now
            await limiter.record("alice")
            await limiter.record("alice")

            # Record 2 more at t=30
            mock_time.monotonic.return_value = now + 30.0
            await limiter.record("alice")
            await limiter.record("alice")

            # At t=30, all 4 in window => blocked
            assert not await limiter.check("alice", "org-1")

            # At t=61, the first 2 expired, only 2 remain => allowed
            mock_time.monotonic.return_value = now + 61.0
            assert await limiter.check("alice", "org-1")


class TestGetRemaining:
    """get_remaining returns correct count."""

    async def test_remaining_full(self) -> None:
        limiter = UserRateLimiter(default_rpm=10)
        # Burst cap = 15; no requests yet => 15 remaining
        assert limiter.get_remaining("alice") == 15

    async def test_remaining_after_requests(self) -> None:
        limiter = UserRateLimiter(default_rpm=10, burst_multiplier=1.5)
        for _ in range(7):
            await limiter.record("alice")
        # burst cap = 15, used 7 => 8 remaining
        assert limiter.get_remaining("alice") == 8

    async def test_remaining_never_negative(self) -> None:
        limiter = UserRateLimiter(default_rpm=3, burst_multiplier=1.0)
        for _ in range(5):
            await limiter.record("alice")
        assert limiter.get_remaining("alice") == 0


class TestGetResetTime:
    """get_reset_time returns seconds until window resets."""

    async def test_reset_time_no_requests(self) -> None:
        limiter = UserRateLimiter(default_rpm=10)
        # No requests => full window
        reset = limiter.get_reset_time("alice")
        assert reset == pytest.approx(60.0, abs=1.0)

    async def test_reset_time_after_requests(self) -> None:
        limiter = UserRateLimiter(default_rpm=10)
        await limiter.record("alice")
        reset = limiter.get_reset_time("alice")
        # Should be close to 60s (oldest entry is ~now)
        assert 58.0 <= reset <= 60.0
