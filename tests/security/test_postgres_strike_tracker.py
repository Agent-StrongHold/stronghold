"""Integration tests for PostgresStrikeTracker (PR-4, BACKLOG R22).

These tests run against a real PostgreSQL instance so we can verify:

* strikes persist across a fresh tracker instance (process restart)
* concurrent ``record_violation`` calls from two tracker instances
  serialize correctly and no strikes are lost
* strike counts, scrutiny levels, lockout, disabled flag, appeals, and the
  violations history all round-trip through the DB
* the 012 migration applies cleanly on an empty database

The tests skip if ``STRONGHOLD_TEST_DATABASE_URL`` is not set, so they are
safe to run in CI environments without a Postgres fixture.  To run locally::

    docker run --rm -d -p 5555:5432 \\
        -e POSTGRES_PASSWORD=stronghold -e POSTGRES_DB=stronghold_test \\
        --name pg-sh-test postgres:16
    export STRONGHOLD_TEST_DATABASE_URL=postgresql://postgres:stronghold@localhost:5555/stronghold_test
    pytest tests/security/test_postgres_strike_tracker.py -v

No mocks are used -- only real asyncpg connections against a real database.
The in-memory tracker's unit tests (test_strikes_coverage.py) continue to
validate the InMemoryStrikeTracker variant which is still used as the
dev/test fallback when DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from stronghold.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    LOCKOUT_DURATION,
    NORMAL,
)

if TYPE_CHECKING:
    import asyncpg

# Skip the whole module when no test DB is configured.
_DB_URL = os.environ.get("STRONGHOLD_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    _DB_URL is None,
    reason="STRONGHOLD_TEST_DATABASE_URL not set -- skipping pg integration tests",
)


# ── Migration helpers ───────────────────────────────────────────────────

_MIGRATION_FILENAME = "012_sentinel_strikes.sql"


def _find_migration() -> Path:
    """Locate the 012 migration file relative to the repo root."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "migrations" / _MIGRATION_FILENAME
        if candidate.exists():
            return candidate
    msg = f"Could not locate {_MIGRATION_FILENAME} above {here}"
    raise RuntimeError(msg)


async def _apply_migration(pool: asyncpg.Pool) -> None:
    """Drop and re-create the sentinel strikes tables on each test run."""
    migration_sql = _find_migration().read_text()
    async with pool.acquire() as conn:
        await conn.execute(
            "DROP TABLE IF EXISTS sentinel_strike_violations CASCADE;"
            "DROP TABLE IF EXISTS sentinel_strikes CASCADE;"
        )
        await conn.execute(migration_sql)


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
async def pg_pool() -> asyncpg.Pool:
    """Connection pool against the test Postgres instance."""
    import asyncpg  # noqa: PLC0415

    assert _DB_URL is not None
    pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=5)
    assert pool is not None
    try:
        await _apply_migration(pool)
        yield pool
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DROP TABLE IF EXISTS sentinel_strike_violations CASCADE;"
                "DROP TABLE IF EXISTS sentinel_strikes CASCADE;"
            )
        await pool.close()


@pytest.fixture
def tracker(pg_pool: asyncpg.Pool) -> PostgresStrikeTracker:  # noqa: F821
    from stronghold.persistence.pg_strikes import PostgresStrikeTracker  # noqa: PLC0415

    return PostgresStrikeTracker(pg_pool)


# ═══════════════════════════════════════════════════════════════════════
# Migration
# ═══════════════════════════════════════════════════════════════════════


class TestMigration:
    """012 migration applies cleanly and creates the expected schema."""

    async def test_tables_exist(self, pg_pool: asyncpg.Pool) -> None:
        async with pg_pool.acquire() as conn:
            strikes = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'sentinel_strikes')"
            )
            violations = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'sentinel_strike_violations')"
            )
        assert strikes is True
        assert violations is True

    async def test_sentinel_strikes_columns(self, pg_pool: asyncpg.Pool) -> None:
        async with pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'sentinel_strikes'"
            )
        cols = {r["column_name"] for r in rows}
        # Every dataclass field on StrikeRecord is represented in the table.
        expected = {
            "user_id",
            "org_id",
            "strike_count",
            "scrutiny_level",
            "locked_until",
            "disabled",
            "last_violation_at",
            "last_appeal",
            "last_appeal_at",
        }
        missing = expected - cols
        assert not missing, f"missing columns: {missing}"


# ═══════════════════════════════════════════════════════════════════════
# Persistence across tracker instances (simulates process restart)
# ═══════════════════════════════════════════════════════════════════════


class TestPersistence:
    """Strike state survives across tracker instances sharing a pool."""

    async def test_strike_persists_across_instances(
        self,
        pg_pool: asyncpg.Pool,
    ) -> None:
        from stronghold.persistence.pg_strikes import PostgresStrikeTracker  # noqa: PLC0415

        t1 = PostgresStrikeTracker(pg_pool)
        await t1.record_violation(
            user_id="persist_user",
            org_id="acme",
            flags=("injection",),
            boundary="user_input",
            detail="first violation",
        )

        # New tracker instance == simulated process restart.
        t2 = PostgresStrikeTracker(pg_pool)
        record = await t2.get("persist_user")

        assert record is not None
        assert record.strike_count == 1
        assert record.scrutiny_level == ELEVATED
        assert record.org_id == "acme"
        assert len(record.violations) == 1
        assert record.violations[0].flags == ("injection",)
        assert record.violations[0].detail == "first violation"

    async def test_unknown_user_returns_none(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        assert await tracker.get("no_such_user") is None


# ═══════════════════════════════════════════════════════════════════════
# Escalation ladder (mirrors test_strikes_coverage.py)
# ═══════════════════════════════════════════════════════════════════════


class TestEscalation:
    """Warn -> lock -> disable escalation, identical to InMemoryStrikeTracker."""

    async def test_strike_1_elevated(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        r = await tracker.record_violation(
            user_id="u1",
            org_id="acme",
            flags=("f",),
        )
        assert r.strike_count == 1
        assert r.scrutiny_level == ELEVATED
        assert r.disabled is False
        assert r.locked_until is None

    async def test_strike_2_locked(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(2):
            r = await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        assert r.strike_count == 2
        assert r.scrutiny_level == LOCKED
        assert r.locked_until is not None
        assert r.disabled is False
        expected_min = datetime.now(UTC) + LOCKOUT_DURATION - timedelta(seconds=10)
        assert r.locked_until >= expected_min
        assert r.is_locked is True

    async def test_strike_3_disabled(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(3):
            r = await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        assert r.strike_count == 3
        assert r.scrutiny_level == DISABLED
        assert r.disabled is True
        assert r.is_locked is True

    async def test_violations_accumulate_ordered(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        await tracker.record_violation(
            user_id="u1", org_id="acme", flags=("first",), boundary="user_input"
        )
        await tracker.record_violation(
            user_id="u1", org_id="acme", flags=("second",), boundary="tool_result"
        )
        record = await tracker.get("u1")
        assert record is not None
        assert len(record.violations) == 2
        assert record.violations[0].flags == ("first",)
        assert record.violations[0].boundary == "user_input"
        assert record.violations[1].flags == ("second",)
        assert record.violations[1].boundary == "tool_result"


# ═══════════════════════════════════════════════════════════════════════
# Concurrency: no lost updates under multi-replica writers
# ═══════════════════════════════════════════════════════════════════════


class TestConcurrency:
    """Two trackers on the same pool must not lose strikes under concurrency."""

    async def test_concurrent_violations_no_lost_updates(
        self,
        pg_pool: asyncpg.Pool,
    ) -> None:
        from stronghold.persistence.pg_strikes import PostgresStrikeTracker  # noqa: PLC0415

        t1 = PostgresStrikeTracker(pg_pool)
        t2 = PostgresStrikeTracker(pg_pool)

        async def hit(tracker: PostgresStrikeTracker) -> None:
            await tracker.record_violation(
                user_id="race_user",
                org_id="acme",
                flags=("race",),
            )

        # 10 concurrent violations split across two "replicas".
        tasks = [hit(t1 if i % 2 == 0 else t2) for i in range(10)]
        await asyncio.gather(*tasks)

        record = await t1.get("race_user")
        assert record is not None
        # Every single violation must have landed.  If SELECT FOR UPDATE
        # were missing, this would typically be less than 10.
        assert record.strike_count == 10
        assert len(record.violations) == 10
        # count >= 3 so the user ends up DISABLED.
        assert record.disabled is True
        assert record.scrutiny_level == DISABLED


# ═══════════════════════════════════════════════════════════════════════
# Admin actions: remove_strikes / unlock / enable / submit_appeal
# ═══════════════════════════════════════════════════════════════════════


class TestAdminActions:
    async def test_remove_strikes_clear_all(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(3):
            await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        r = await tracker.remove_strikes("u1", count=None)
        assert r is not None
        assert r.strike_count == 0
        assert r.scrutiny_level == NORMAL
        assert r.disabled is False
        assert r.locked_until is None

    async def test_remove_strikes_partial(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(3):
            await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        r = await tracker.remove_strikes("u1", count=2)
        assert r is not None
        assert r.strike_count == 1
        assert r.scrutiny_level == ELEVATED
        assert r.disabled is False
        assert r.locked_until is None

    async def test_remove_strikes_clamps_at_zero(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        r = await tracker.remove_strikes("u1", count=10)
        assert r is not None
        assert r.strike_count == 0
        assert r.scrutiny_level == NORMAL

    async def test_remove_strikes_unknown_user(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        assert await tracker.remove_strikes("ghost") is None

    async def test_unlock_clears_lockout_keeps_strikes(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(2):
            await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        r = await tracker.unlock("u1")
        assert r is not None
        assert r.locked_until is None
        assert r.strike_count == 2
        assert r.scrutiny_level == ELEVATED
        assert r.is_locked is False

    async def test_unlock_disabled_stays_disabled(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(3):
            await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        r = await tracker.unlock("u1")
        assert r is not None
        assert r.disabled is True
        assert r.is_locked is True

    async def test_unlock_unknown_user(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        assert await tracker.unlock("ghost") is None

    async def test_enable_clears_disabled(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        for _ in range(3):
            await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        r = await tracker.enable("u1")
        assert r is not None
        assert r.disabled is False
        assert r.locked_until is None
        assert r.scrutiny_level == ELEVATED
        assert r.strike_count == 3
        assert r.is_locked is False

    async def test_enable_unknown_user(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        assert await tracker.enable("ghost") is None

    async def test_submit_appeal_success(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        ok = await tracker.submit_appeal("u1", "please reconsider")
        assert ok is True
        r = await tracker.get("u1")
        assert r is not None
        assert r.last_appeal == "please reconsider"
        assert r.last_appeal_at is not None

    async def test_submit_appeal_unknown_user(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        assert await tracker.submit_appeal("ghost", "please") is False

    async def test_submit_appeal_zero_strikes(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        await tracker.remove_strikes("u1", count=None)
        assert await tracker.submit_appeal("u1", "please") is False


# ═══════════════════════════════════════════════════════════════════════
# get_all_for_org
# ═══════════════════════════════════════════════════════════════════════


class TestGetAllForOrg:
    async def test_returns_org_users_only(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        await tracker.record_violation(user_id="u1", org_id="acme", flags=("f",))
        await tracker.record_violation(user_id="u2", org_id="acme", flags=("f",))
        await tracker.record_violation(user_id="u3", org_id="other", flags=("f",))

        acme = await tracker.get_all_for_org("acme")
        assert {r.user_id for r in acme} == {"u1", "u2"}

        other = await tracker.get_all_for_org("other")
        assert {r.user_id for r in other} == {"u3"}

    async def test_empty_org(
        self,
        tracker: PostgresStrikeTracker,  # noqa: F821
    ) -> None:
        assert await tracker.get_all_for_org("nonexistent") == []
