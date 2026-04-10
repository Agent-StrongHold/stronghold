"""Tests for RedisPromptCache."""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from stronghold.cache.prompt_cache import RedisPromptCache


@pytest.fixture
async def redis_client() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


async def test_get_miss_returns_none(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    assert await cache.get("missing") is None


async def test_set_then_get(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    await cache.set("agent.ranger", {"model": "gemini", "tools": ["web"]})
    result = await cache.get("agent.ranger")
    assert result == {"model": "gemini", "tools": ["web"]}


async def test_set_string_value(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    await cache.set("key", "hello")
    assert await cache.get("key") == "hello"


async def test_set_with_custom_ttl(redis_client) -> None:
    cache = RedisPromptCache(redis_client, ttl_seconds=300)
    await cache.set("key", "v", ttl=60)
    # TTL should be set — fakeredis supports ttl() query
    ttl = await redis_client.ttl("stronghold:cache:key")
    assert 0 < ttl <= 60


async def test_set_default_ttl(redis_client) -> None:
    cache = RedisPromptCache(redis_client, ttl_seconds=300)
    await cache.set("key", "v")
    ttl = await redis_client.ttl("stronghold:cache:key")
    assert 0 < ttl <= 300


async def test_delete_invalidates(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    await cache.set("key", "value")
    assert await cache.get("key") == "value"
    await cache.delete("key")
    assert await cache.get("key") is None


async def test_delete_missing_is_noop(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    await cache.delete("never-existed")  # should not raise


async def test_key_prefix_isolation(redis_client) -> None:
    a = RedisPromptCache(redis_client, key_prefix="a:")
    b = RedisPromptCache(redis_client, key_prefix="b:")
    await a.set("k", "a_value")
    await b.set("k", "b_value")
    assert await a.get("k") == "a_value"
    assert await b.get("k") == "b_value"


async def test_invalidate_pattern_removes_matching(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    await cache.set("agent.ranger", "r")
    await cache.set("agent.scribe", "s")
    await cache.set("prompt.hello", "h")
    await cache.invalidate_pattern("agent.*")
    assert await cache.get("agent.ranger") is None
    assert await cache.get("agent.scribe") is None
    assert await cache.get("prompt.hello") == "h"


async def test_invalidate_pattern_empty_set_is_noop(redis_client) -> None:
    cache = RedisPromptCache(redis_client)
    await cache.invalidate_pattern("nothing.*")  # Should not raise


async def test_json_serializes_dates(redis_client) -> None:
    """default=str handler should serialize datetime objects."""
    import datetime
    cache = RedisPromptCache(redis_client)
    now = datetime.datetime(2026, 1, 15, 10, 30)
    await cache.set("key", {"created_at": now})
    result = await cache.get("key")
    # Date gets serialized as string
    assert "created_at" in result
