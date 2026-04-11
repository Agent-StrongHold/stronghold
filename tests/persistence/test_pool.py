"""Tests for persistence pool management and migrations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def _reset_pool() -> None:
    import stronghold.persistence as mod
    if mod._pool is not None:
        try:
            await mod._pool.close()
        except Exception:
            pass
    mod._pool = None


async def test_get_pool_creates_on_first_call() -> None:
    import stronghold.persistence as mod
    await _reset_pool()

    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()

    async def fake_create_pool(*args, **kwargs):
        return fake_pool

    with patch.object(mod.asyncpg, "create_pool", side_effect=fake_create_pool):
        result = await mod.get_pool("postgresql://user:pass@host/db")
        assert result is fake_pool

    await _reset_pool()


async def test_get_pool_returns_cached_on_second_call() -> None:
    import stronghold.persistence as mod
    await _reset_pool()

    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()
    call_count = {"n": 0}

    async def fake_create_pool(*args, **kwargs):
        call_count["n"] += 1
        return fake_pool

    with patch.object(mod.asyncpg, "create_pool", side_effect=fake_create_pool):
        r1 = await mod.get_pool("postgresql://host/db")
        r2 = await mod.get_pool("postgresql://host/db")
        assert r1 is r2
        assert call_count["n"] == 1  # Only created once

    await _reset_pool()


async def test_close_pool_clears_reference() -> None:
    import stronghold.persistence as mod
    await _reset_pool()

    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()
    mod._pool = fake_pool

    await mod.close_pool()
    assert mod._pool is None
    fake_pool.close.assert_awaited_once()


async def test_close_pool_when_none() -> None:
    """Closing when no pool exists is a no-op, not an error."""
    import stronghold.persistence as mod
    await _reset_pool()
    await mod.close_pool()  # should not raise
    assert mod._pool is None


# ── Migrations ──────────────────────────────────────────────────────


async def test_run_migrations_missing_dir() -> None:
    """Missing migrations directory logs warning but does not raise."""
    from stronghold.persistence import run_migrations
    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock()
    # Should return without calling acquire
    await run_migrations(fake_pool, migrations_dir="/does/not/exist")
    fake_pool.acquire.assert_not_called()


async def test_run_migrations_empty_dir(tmp_path: Path) -> None:
    """Empty migrations directory creates _migrations table but applies nothing."""
    from stronghold.persistence import run_migrations

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()

    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.fetchval = AsyncMock(return_value=False)

    class FakeAcquireCtx:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=FakeAcquireCtx())

    await run_migrations(fake_pool, migrations_dir=str(mig_dir))
    # Should have executed the CREATE TABLE _migrations
    assert any(
        "CREATE TABLE" in str(call.args[0]) for call in fake_conn.execute.call_args_list
    )


async def test_run_migrations_applies_new_files(tmp_path: Path) -> None:
    from stronghold.persistence import run_migrations

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001_init.sql").write_text("CREATE TABLE agents (id INT);")
    (mig_dir / "002_add_index.sql").write_text("CREATE INDEX idx ON agents(id);")

    execute_calls = []
    fake_conn = MagicMock()
    async def fake_execute(sql, *args):
        execute_calls.append(sql)
    fake_conn.execute = AsyncMock(side_effect=fake_execute)
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.fetchval = AsyncMock(return_value=False)

    class FakeAcquireCtx:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=FakeAcquireCtx())

    await run_migrations(fake_pool, migrations_dir=str(mig_dir))
    # Both SQL files should have been executed
    assert any("CREATE TABLE agents" in str(c) for c in execute_calls)
    assert any("CREATE INDEX" in str(c) for c in execute_calls)


async def test_run_migrations_skips_already_applied(tmp_path: Path) -> None:
    from stronghold.persistence import run_migrations

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001.sql").write_text("CREATE TABLE x (id INT);")
    (mig_dir / "002.sql").write_text("CREATE TABLE y (id INT);")

    execute_calls = []
    fake_conn = MagicMock()
    async def fake_execute(sql, *args):
        execute_calls.append(sql)
    fake_conn.execute = AsyncMock(side_effect=fake_execute)
    # 001.sql already applied
    fake_conn.fetch = AsyncMock(return_value=[{"name": "001.sql"}])
    fake_conn.fetchval = AsyncMock(return_value=False)

    class FakeAcquireCtx:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=FakeAcquireCtx())

    await run_migrations(fake_pool, migrations_dir=str(mig_dir))
    # Only 002.sql should have been applied
    assert any("CREATE TABLE y" in str(c) for c in execute_calls)
    assert not any("CREATE TABLE x" in str(c) for c in execute_calls)


async def test_run_migrations_marks_preexisting_as_applied(tmp_path: Path) -> None:
    """If tables exist but _migrations empty, treat existing migrations as applied."""
    from stronghold.persistence import run_migrations

    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir()
    (mig_dir / "001.sql").write_text("CREATE TABLE agents (id INT);")

    insert_calls = []
    fake_conn = MagicMock()
    async def fake_execute(sql, *args):
        if "INSERT INTO _migrations" in sql:
            insert_calls.append(args)
    fake_conn.execute = AsyncMock(side_effect=fake_execute)
    fake_conn.fetch = AsyncMock(return_value=[])  # no applied migrations
    fake_conn.fetchval = AsyncMock(return_value=True)  # but tables exist

    class FakeAcquireCtx:
        async def __aenter__(self): return fake_conn
        async def __aexit__(self, *a): return None

    fake_pool = MagicMock()
    fake_pool.acquire = MagicMock(return_value=FakeAcquireCtx())

    await run_migrations(fake_pool, migrations_dir=str(mig_dir))
    # Should have marked the existing migration as applied
    assert len(insert_calls) == 1
    assert insert_calls[0] == ("001.sql",)


async def test_run_migrations_default_dir_search(tmp_path: Path, monkeypatch) -> None:
    """When migrations_dir not provided, searches candidate paths."""
    from stronghold.persistence import run_migrations

    # Use a non-existent dir so we hit the warning path
    fake_pool = MagicMock()
    await run_migrations(fake_pool)  # should not raise
