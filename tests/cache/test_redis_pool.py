"""Tests for the Redis connection-pool singleton + URL masking."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from stronghold.cache import redis_pool
from stronghold.cache.redis_pool import _mask_url, close_redis, get_redis


@pytest.fixture(autouse=True)
def _reset_pool() -> None:
    """Every test starts with no pool so singleton state doesn't leak."""
    redis_pool._pool = None
    yield
    redis_pool._pool = None


class TestMaskUrl:
    def test_no_credentials_returns_original(self) -> None:
        assert _mask_url("redis://localhost:6379/0") == "redis://localhost:6379/0"

    def test_password_only_masked(self) -> None:
        masked = _mask_url("redis://:secret@localhost:6379/0")
        assert "secret" not in masked
        assert "***" in masked
        assert "localhost:6379" in masked

    def test_username_and_password_masked(self) -> None:
        masked = _mask_url("redis://alice:secret@cache.internal:6380/2")
        assert "alice" not in masked
        assert "secret" not in masked
        assert "cache.internal:6380" in masked
        assert "/2" in masked

    def test_missing_port_still_masks_host(self) -> None:
        masked = _mask_url("redis://user:pw@cache.internal/1")
        assert "pw" not in masked
        assert "cache.internal" in masked

    def test_invalid_url_falls_back_to_opaque_mask(self) -> None:
        """Any parsing failure must not leak the raw URL.

        _mask_url does `from urllib.parse import urlparse` inside the
        function, so patching the canonical location covers both the
        import and any call chain."""
        with patch("urllib.parse.urlparse", side_effect=ValueError):
            result = _mask_url("anything")
        assert result == "redis://***"


class TestPoolSingleton:
    @pytest.mark.asyncio
    async def test_get_redis_creates_pool_on_first_call(self) -> None:
        fake = AsyncMock()
        fake.ping = AsyncMock(return_value=True)
        with patch(
            "stronghold.cache.redis_pool.aioredis.from_url", return_value=fake
        ) as from_url:
            pool = await get_redis("redis://localhost:6379/0")
        assert pool is fake
        from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_redis_returns_cached_pool_on_second_call(self) -> None:
        fake = AsyncMock()
        fake.ping = AsyncMock(return_value=True)
        with patch(
            "stronghold.cache.redis_pool.aioredis.from_url", return_value=fake
        ) as from_url:
            first = await get_redis("redis://localhost:6379/0")
            second = await get_redis("redis://localhost:6379/0")
        assert first is second
        assert from_url.call_count == 1  # constructor called only once

    @pytest.mark.asyncio
    async def test_get_redis_pings_on_create(self) -> None:
        fake = AsyncMock()
        fake.ping = AsyncMock(return_value=True)
        with patch(
            "stronghold.cache.redis_pool.aioredis.from_url", return_value=fake
        ):
            await get_redis()
        fake.ping.assert_awaited_once()


class TestPoolClose:
    @pytest.mark.asyncio
    async def test_close_when_no_pool_is_noop(self) -> None:
        # Should not raise — singleton is None.
        await close_redis()

    @pytest.mark.asyncio
    async def test_close_calls_aclose_and_clears_singleton(self) -> None:
        fake = AsyncMock()
        fake.ping = AsyncMock(return_value=True)
        fake.aclose = AsyncMock()
        with patch(
            "stronghold.cache.redis_pool.aioredis.from_url", return_value=fake
        ):
            await get_redis()
        await close_redis()
        fake.aclose.assert_awaited_once()
        assert redis_pool._pool is None

    @pytest.mark.asyncio
    async def test_get_redis_after_close_creates_fresh_pool(self) -> None:
        fake1 = AsyncMock()
        fake1.ping = AsyncMock(return_value=True)
        fake1.aclose = AsyncMock()
        fake2 = AsyncMock()
        fake2.ping = AsyncMock(return_value=True)
        with patch(
            "stronghold.cache.redis_pool.aioredis.from_url",
            side_effect=[fake1, fake2],
        ):
            a = await get_redis()
            await close_redis()
            b = await get_redis()
        assert a is fake1
        assert b is fake2
        assert a is not b
