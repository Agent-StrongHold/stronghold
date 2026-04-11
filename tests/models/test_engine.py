"""Tests for SQLAlchemy async engine lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _reset_engine() -> None:
    import stronghold.models.engine as mod
    if mod._engine is not None:
        try:
            await mod._engine.dispose()
        except Exception:
            pass
    mod._engine = None
    mod._engine_url = ""


async def test_get_engine_creates_on_first_call() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    with patch("stronghold.models.engine.create_async_engine", return_value=fake_engine):
        engine = mod.get_engine("postgresql://user@host/db")
        assert engine is fake_engine

    await _reset_engine()


async def test_get_engine_converts_postgresql_to_asyncpg() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()

    created_urls = []
    def capture(url, **kwargs):
        created_urls.append(url)
        return MagicMock(dispose=AsyncMock())

    with patch("stronghold.models.engine.create_async_engine", side_effect=capture):
        mod.get_engine("postgresql://user@host/db")

    assert created_urls[0] == "postgresql+asyncpg://user@host/db"
    await _reset_engine()


async def test_get_engine_converts_postgres_alias() -> None:
    """'postgres://' is an alias for 'postgresql://' — both should be normalized."""
    import stronghold.models.engine as mod
    await _reset_engine()

    created_urls = []
    def capture(url, **kwargs):
        created_urls.append(url)
        return MagicMock(dispose=AsyncMock())

    with patch("stronghold.models.engine.create_async_engine", side_effect=capture):
        mod.get_engine("postgres://user@host/db")

    assert created_urls[0] == "postgresql+asyncpg://user@host/db"
    await _reset_engine()


async def test_get_engine_returns_cached_on_same_url() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()

    count = {"n": 0}
    def capture(url, **kwargs):
        count["n"] += 1
        return MagicMock(dispose=AsyncMock())

    with patch("stronghold.models.engine.create_async_engine", side_effect=capture):
        e1 = mod.get_engine("postgresql://host/db")
        e2 = mod.get_engine("postgresql://host/db")

    assert e1 is e2
    assert count["n"] == 1
    await _reset_engine()


async def test_get_engine_rejects_different_url() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()

    with patch("stronghold.models.engine.create_async_engine",
               return_value=MagicMock(dispose=AsyncMock())):
        mod.get_engine("postgresql://host1/db")
        with pytest.raises(RuntimeError, match="different URL"):
            mod.get_engine("postgresql://host2/db")

    await _reset_engine()


async def test_get_engine_same_url_reuses_silently() -> None:
    """Passing the same URL twice must not raise even after initialization."""
    import stronghold.models.engine as mod
    await _reset_engine()

    with patch("stronghold.models.engine.create_async_engine",
               return_value=MagicMock(dispose=AsyncMock())):
        e1 = mod.get_engine("postgresql://host/db")
        e2 = mod.get_engine("postgresql://host/db")  # should not raise
        assert e1 is e2

    await _reset_engine()


async def test_get_engine_empty_url_after_init_returns_cached() -> None:
    """Passing empty URL after initialization returns the existing engine."""
    import stronghold.models.engine as mod
    await _reset_engine()

    fake = MagicMock(dispose=AsyncMock())
    with patch("stronghold.models.engine.create_async_engine", return_value=fake):
        mod.get_engine("postgresql://host/db")
        # Empty URL should not trigger the "different URL" check
        e2 = mod.get_engine("")
        assert e2 is fake

    await _reset_engine()


async def test_close_engine() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()

    fake = MagicMock()
    fake.dispose = AsyncMock()
    mod._engine = fake
    mod._engine_url = "postgresql://x"

    await mod.close_engine()
    fake.dispose.assert_awaited_once()
    assert mod._engine is None
    assert mod._engine_url == ""


async def test_close_engine_when_none() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()
    await mod.close_engine()  # must not raise


async def test_get_session_without_engine_raises() -> None:
    """get_session with no URL and no initialized engine must raise clearly."""
    import stronghold.models.engine as mod
    await _reset_engine()

    with pytest.raises(RuntimeError, match="not initialized"):
        async with mod.get_session():
            pass


async def test_get_session_with_url_initializes_engine() -> None:
    import stronghold.models.engine as mod
    await _reset_engine()

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock()

    class FakeSessionCtx:
        async def __aenter__(self): return MagicMock()
        async def __aexit__(self, *a): return None

    with patch("stronghold.models.engine.create_async_engine", return_value=fake_engine), \
         patch("stronghold.models.engine.AsyncSession", return_value=FakeSessionCtx()):
        async with mod.get_session("postgresql://host/db") as session:
            assert session is not None

    await _reset_engine()
