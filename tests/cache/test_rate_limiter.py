"""Tests for RedisRateLimiter (sliding window algorithm)."""

from __future__ import annotations

import asyncio
import time

import fakeredis.aioredis
import pytest

from stronghold.cache.rate_limiter import RedisRateLimiter


@pytest.fixture
async def redis_client() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


async def test_first_request_allowed(redis_client) -> None:
    limiter = RedisRateLimiter(redis_client, max_requests=5, window_seconds=60)
    allowed, headers = await limiter.check("user:alice")
    assert allowed is True
    assert headers["X-RateLimit-Limit"] == "5"
    assert headers["X-RateLimit-Remaining"] == "5"


async def test_record_then_check_shows_usage(redis_client) -> None:
    limiter = RedisRateLimiter(redis_client, max_requests=5, window_seconds=60)
    await limiter.record("user:alice")
    await limiter.record("user:alice")
    allowed, headers = await limiter.check("user:alice")
    assert allowed is True
    assert headers["X-RateLimit-Remaining"] == "3"


async def test_exact_limit_blocks(redis_client) -> None:
    limiter = RedisRateLimiter(redis_client, max_requests=3, window_seconds=60)
    for _ in range(3):
        await limiter.record("user:alice")
    allowed, headers = await limiter.check("user:alice")
    assert allowed is False
    assert headers["X-RateLimit-Remaining"] == "0"


async def test_different_keys_independent(redis_client) -> None:
    limiter = RedisRateLimiter(redis_client, max_requests=2, window_seconds=60)
    await limiter.record("user:alice")
    await limiter.record("user:alice")
    allowed_alice, _ = await limiter.check("user:alice")
    allowed_bob, _ = await limiter.check("user:bob")
    assert allowed_alice is False
    assert allowed_bob is True


async def test_key_prefix_isolation(redis_client) -> None:
    """Different prefixes must not interfere."""
    a = RedisRateLimiter(redis_client, max_requests=2, window_seconds=60, key_prefix="a:")
    b = RedisRateLimiter(redis_client, max_requests=2, window_seconds=60, key_prefix="b:")
    await a.record("user:alice")
    await a.record("user:alice")
    allowed_a, _ = await a.check("user:alice")
    allowed_b, _ = await b.check("user:alice")
    assert allowed_a is False
    assert allowed_b is True


async def test_reset_seconds_when_empty(redis_client) -> None:
    """Reset returns the full window when no requests recorded."""
    limiter = RedisRateLimiter(redis_client, max_requests=5, window_seconds=120)
    _, headers = await limiter.check("user:alice")
    assert int(headers["X-RateLimit-Reset"]) == 120


async def test_reset_seconds_from_oldest_entry(redis_client) -> None:
    """Reset counts down from the oldest entry in the window."""
    limiter = RedisRateLimiter(redis_client, max_requests=5, window_seconds=60)
    await limiter.record("user:alice")
    _, headers = await limiter.check("user:alice")
    reset = int(headers["X-RateLimit-Reset"])
    # Should be close to 60 (the window), not 0
    assert 55 <= reset <= 60


async def test_expired_entries_evicted(redis_client) -> None:
    """Entries older than window_start are pruned."""
    limiter = RedisRateLimiter(redis_client, max_requests=2, window_seconds=1)
    await limiter.record("user:alice")
    await limiter.record("user:alice")
    allowed, _ = await limiter.check("user:alice")
    assert allowed is False
    # Wait for entries to expire
    await asyncio.sleep(1.1)
    allowed_after, headers_after = await limiter.check("user:alice")
    assert allowed_after is True
    assert headers_after["X-RateLimit-Remaining"] == "2"


async def test_concurrent_records_same_timestamp(redis_client) -> None:
    """Multiple records at the 'same' timestamp must not collide (unique member suffix)."""
    limiter = RedisRateLimiter(redis_client, max_requests=10, window_seconds=60)
    await asyncio.gather(*[limiter.record("user:alice") for _ in range(5)])
    _, headers = await limiter.check("user:alice")
    # All 5 recorded — if member collisions occurred, count would be < 5
    assert headers["X-RateLimit-Remaining"] == "5"
