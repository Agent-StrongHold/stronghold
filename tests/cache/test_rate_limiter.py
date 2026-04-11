"""Tests for RedisRateLimiter (sliding window log)."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from stronghold.cache.rate_limiter import RedisRateLimiter


@pytest.fixture
async def limiter() -> RedisRateLimiter:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    return RedisRateLimiter(
        redis=redis, max_requests=3, window_seconds=60, key_prefix="rl:"
    )


class TestCheckAllowed:
    @pytest.mark.asyncio
    async def test_first_request_allowed(
        self, limiter: RedisRateLimiter
    ) -> None:
        allowed, headers = await limiter.check("user:alice")
        assert allowed is True
        assert headers["X-RateLimit-Limit"] == "3"
        assert headers["X-RateLimit-Remaining"] == "3"

    @pytest.mark.asyncio
    async def test_under_budget_allowed(
        self, limiter: RedisRateLimiter
    ) -> None:
        await limiter.record("user:alice")
        await limiter.record("user:alice")
        allowed, headers = await limiter.check("user:alice")
        assert allowed is True
        assert headers["X-RateLimit-Remaining"] == "1"

    @pytest.mark.asyncio
    async def test_at_budget_still_allowed(
        self, limiter: RedisRateLimiter
    ) -> None:
        """max=3 means the 3rd request is still OK; the 4th is blocked."""
        for _ in range(2):
            await limiter.record("user:alice")
        allowed, headers = await limiter.check("user:alice")
        assert allowed is True
        assert headers["X-RateLimit-Remaining"] == "1"

    @pytest.mark.asyncio
    async def test_over_budget_blocked(
        self, limiter: RedisRateLimiter
    ) -> None:
        for _ in range(3):
            await limiter.record("user:alice")
        allowed, headers = await limiter.check("user:alice")
        assert allowed is False
        assert headers["X-RateLimit-Remaining"] == "0"


class TestIsolation:
    @pytest.mark.asyncio
    async def test_separate_keys_have_separate_budgets(
        self, limiter: RedisRateLimiter
    ) -> None:
        for _ in range(3):
            await limiter.record("user:alice")
        # alice maxed
        allowed_alice, _ = await limiter.check("user:alice")
        assert allowed_alice is False
        # bob fresh
        allowed_bob, _ = await limiter.check("user:bob")
        assert allowed_bob is True

    @pytest.mark.asyncio
    async def test_record_adds_unique_members(
        self, limiter: RedisRateLimiter
    ) -> None:
        """Two records at the same timestamp must both count (no collision)."""
        await limiter.record("user:burst")
        await limiter.record("user:burst")
        _, headers = await limiter.check("user:burst")
        assert headers["X-RateLimit-Remaining"] == "1"  # 2 used, 1 left


class TestResetHeader:
    @pytest.mark.asyncio
    async def test_empty_window_reset_equals_window_size(
        self, limiter: RedisRateLimiter
    ) -> None:
        _, headers = await limiter.check("user:fresh")
        assert headers["X-RateLimit-Reset"] == "60"

    @pytest.mark.asyncio
    async def test_populated_window_reset_is_positive(
        self, limiter: RedisRateLimiter
    ) -> None:
        await limiter.record("user:x")
        _, headers = await limiter.check("user:x")
        reset = int(headers["X-RateLimit-Reset"])
        # Should be <= 60 (window size) and >= 0
        assert 0 <= reset <= 60


class TestWindowEviction:
    @pytest.mark.asyncio
    async def test_expired_entries_evicted_on_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Entries older than the window must not count against the budget.
        Simulated by moving time forward via monkey-patching time.time."""
        redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        lim = RedisRateLimiter(
            redis=redis, max_requests=2, window_seconds=10, key_prefix="rl2:"
        )
        # Fill the budget at t=1000
        base_t = [1000.0]
        import time as _time

        monkeypatch.setattr(_time, "time", lambda: base_t[0])
        await lim.record("user:zoe")
        await lim.record("user:zoe")
        allowed_at_full, _ = await lim.check("user:zoe")
        assert allowed_at_full is False

        # Move time 20s forward — entries are outside the 10s window.
        base_t[0] = 1020.0
        allowed_after_window, headers = await lim.check("user:zoe")
        assert allowed_after_window is True
        assert headers["X-RateLimit-Remaining"] == "2"
