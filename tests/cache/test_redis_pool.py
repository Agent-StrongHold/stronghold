"""Tests for Redis connection pool helpers."""

from __future__ import annotations

from stronghold.cache.redis_pool import _mask_url


def test_mask_url_no_credentials() -> None:
    assert _mask_url("redis://localhost:6379/0") == "redis://localhost:6379/0"


def test_mask_url_with_password() -> None:
    masked = _mask_url("redis://:password123@redis.example.com:6379/0")
    assert "password123" not in masked
    assert "***" in masked
    assert "redis.example.com" in masked
    assert "6379" in masked


def test_mask_url_with_username_and_password() -> None:
    masked = _mask_url("redis://user:secret@host:6379/1")
    assert "secret" not in masked
    assert "user" not in masked
    assert "***" in masked


def test_mask_url_no_port() -> None:
    masked = _mask_url("redis://:pw@example.com/0")
    assert "pw" not in masked
    assert "example.com" in masked


def test_mask_url_with_db_path() -> None:
    masked = _mask_url("redis://:pw@redis.example.com:6379/3")
    assert "pw" not in masked
    assert "/3" in masked


# ── get_redis / close_redis pool management ─────────────────────────


async def test_get_redis_creates_pool(monkeypatch) -> None:
    """get_redis creates a pool lazily on first call."""
    import stronghold.cache.redis_pool as mod
    from unittest.mock import AsyncMock, MagicMock

    # Reset pool
    mod._pool = None

    fake_pool = MagicMock()
    fake_pool.ping = AsyncMock(return_value=True)

    async def fake_from_url(url, **kwargs):
        return fake_pool

    monkeypatch.setattr(mod.aioredis, "from_url", lambda url, **kw: fake_pool)
    result = await mod.get_redis("redis://test:6379/0")
    assert result is fake_pool
    fake_pool.ping.assert_awaited_once()

    # Second call returns cached pool without re-calling ping
    fake_pool.ping.reset_mock()
    result2 = await mod.get_redis("redis://test:6379/0")
    assert result2 is fake_pool
    fake_pool.ping.assert_not_called()

    mod._pool = None


async def test_close_redis_closes_pool(monkeypatch) -> None:
    import stronghold.cache.redis_pool as mod
    from unittest.mock import AsyncMock, MagicMock

    fake_pool = MagicMock()
    fake_pool.aclose = AsyncMock()
    mod._pool = fake_pool

    await mod.close_redis()
    fake_pool.aclose.assert_awaited_once()
    assert mod._pool is None


async def test_close_redis_no_pool_is_noop() -> None:
    import stronghold.cache.redis_pool as mod
    mod._pool = None
    await mod.close_redis()  # Should not raise
    assert mod._pool is None
