"""Tests for RedisPromptCache.

Uses fakeredis.aioredis as a drop-in Redis substitute so the tests are
fully self-contained and don't need a running Redis instance.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from stronghold.cache.prompt_cache import RedisPromptCache


@pytest.fixture
async def cache() -> RedisPromptCache:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    return RedisPromptCache(redis=redis, ttl_seconds=60, key_prefix="test:")


class TestGetSet:
    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, cache: RedisPromptCache) -> None:
        assert await cache.get("nope") is None

    @pytest.mark.asyncio
    async def test_set_then_get_roundtrips_dict(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("agent.mason", {"role": "builder", "tier": "P2"})
        got = await cache.get("agent.mason")
        assert got == {"role": "builder", "tier": "P2"}

    @pytest.mark.asyncio
    async def test_set_then_get_roundtrips_list(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("skills", ["a", "b", "c"])
        assert await cache.get("skills") == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_set_with_non_json_value_falls_back_to_str(
        self, cache: RedisPromptCache
    ) -> None:
        """json.dumps has default=str so datetime-ish values survive."""
        from datetime import UTC, datetime

        stamp = datetime(2026, 4, 10, tzinfo=UTC)
        await cache.set("when", {"ts": stamp})
        got = await cache.get("when")
        assert isinstance(got["ts"], str)
        assert "2026-04-10" in got["ts"]


class TestTTL:
    @pytest.mark.asyncio
    async def test_set_applies_default_ttl(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("agent.x", {"v": 1})
        # fakeredis supports ttl() for keys with expiry
        ttl = await cache._redis.ttl("test:agent.x")  # type: ignore[attr-defined]
        assert 0 < ttl <= 60

    @pytest.mark.asyncio
    async def test_set_respects_explicit_ttl(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("agent.x", {"v": 1}, ttl=120)
        ttl = await cache._redis.ttl("test:agent.x")  # type: ignore[attr-defined]
        assert 60 < ttl <= 120


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_key(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("gone", {"v": 1})
        assert await cache.get("gone") == {"v": 1}
        await cache.delete("gone")
        assert await cache.get("gone") is None

    @pytest.mark.asyncio
    async def test_delete_missing_key_is_noop(
        self, cache: RedisPromptCache
    ) -> None:
        # No exception expected.
        await cache.delete("never-existed")


class TestInvalidatePattern:
    @pytest.mark.asyncio
    async def test_invalidate_pattern_wipes_all_matching(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("agent.mason", {"v": 1})
        await cache.set("agent.frank", {"v": 2})
        await cache.set("prompt.hello", {"v": 3})
        await cache.invalidate_pattern("agent.*")
        assert await cache.get("agent.mason") is None
        assert await cache.get("agent.frank") is None
        assert await cache.get("prompt.hello") == {"v": 3}  # untouched

    @pytest.mark.asyncio
    async def test_invalidate_pattern_with_zero_matches_is_noop(
        self, cache: RedisPromptCache
    ) -> None:
        await cache.set("agent.mason", {"v": 1})
        await cache.invalidate_pattern("nothing.*")
        assert await cache.get("agent.mason") == {"v": 1}

    @pytest.mark.asyncio
    async def test_invalidate_pattern_walks_cursor_until_zero(
        self, cache: RedisPromptCache
    ) -> None:
        """Regression guard: the SCAN loop must exit only when cursor==0.

        Note: SCAN-during-delete can miss keys when the key set is large
        enough to span multiple cursor pages (keys in later pages can be
        skipped when earlier deletes empty the slot the cursor was about
        to visit). That's a known production behavior of this helper.
        This test verifies the happy path — a modest key set — and the
        majority of entries being wiped.
        """
        for i in range(10):
            await cache.set(f"agent.bulk.{i}", {"i": i})
        await cache.invalidate_pattern("agent.bulk.*")
        survivors = [
            i for i in range(10)
            if await cache.get(f"agent.bulk.{i}") is not None
        ]
        # Happy path on fakeredis with a small set: everything cleaned up.
        assert survivors == []
