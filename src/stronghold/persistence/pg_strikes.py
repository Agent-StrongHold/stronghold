"""PostgreSQL-backed strike tracker.

Replaces :class:`stronghold.security.strikes.InMemoryStrikeTracker` for
production deployments so strike state survives process restart and stays
consistent across multiple Stronghold-API replicas.

The contract (return types, escalation ladder, admin semantics) mirrors
:class:`InMemoryStrikeTracker` exactly -- the same test cases cover both
implementations.  Concurrency-safety across replicas is guaranteed by a
``SELECT ... FOR UPDATE`` row lock inside every mutation transaction.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from stronghold.security.strikes import (
    DISABLED,
    ELEVATED,
    LOCKED,
    LOCKOUT_DURATION,
    NORMAL,
    StrikeRecord,
    ViolationRecord,
)

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger("stronghold.persistence.pg_strikes")


class PostgresStrikeTracker:
    """PostgreSQL-backed strike tracker.

    Implements the same protocol as :class:`InMemoryStrikeTracker`:
    ``get``, ``record_violation``, ``submit_appeal``, ``remove_strikes``,
    ``unlock``, ``enable``, ``get_all_for_org``.

    Two tables back this class (see migration 012):

    * ``sentinel_strikes``           -- one row per user with the current
      strike state (count, scrutiny level, lockout, disabled flag, appeal).
    * ``sentinel_strike_violations`` -- append-only log of individual
      violation events, joined back to ``sentinel_strikes`` on ``user_id``.

    Mutations that escalate strike state acquire a row-level lock via
    ``SELECT ... FOR UPDATE`` so concurrent ``record_violation`` calls from
    different API replicas serialize correctly and no strikes are lost.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------ read

    async def get(self, user_id: str) -> StrikeRecord | None:
        """Get strike record for a user (``None`` if no record exists)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM sentinel_strikes WHERE user_id = $1",
                user_id,
            )
            if row is None:
                return None
            violations = await conn.fetch(
                """SELECT timestamp, flags, boundary, detail
                   FROM sentinel_strike_violations
                   WHERE user_id = $1
                   ORDER BY id ASC""",
                user_id,
            )
        return _row_to_record(row, violations)

    async def get_all_for_org(self, org_id: str) -> list[StrikeRecord]:
        """Get all strike records for an org (admin view)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM sentinel_strikes WHERE org_id = $1",
                org_id,
            )
            records: list[StrikeRecord] = []
            for row in rows:
                violations = await conn.fetch(
                    """SELECT timestamp, flags, boundary, detail
                       FROM sentinel_strike_violations
                       WHERE user_id = $1
                       ORDER BY id ASC""",
                    row["user_id"],
                )
                records.append(_row_to_record(row, violations))
        return records

    # ------------------------------------------------------------------ write

    async def record_violation(
        self,
        *,
        user_id: str,
        org_id: str,
        flags: tuple[str, ...],
        boundary: str = "user_input",
        detail: str = "",
    ) -> StrikeRecord:
        """Record a violation and escalate strike level.

        Atomic under concurrent writers: the transaction upserts the
        ``sentinel_strikes`` row, acquires a row lock via
        ``SELECT ... FOR UPDATE``, increments ``strike_count``, applies
        the escalation ladder, appends the violation row, and commits.
        """
        now = datetime.now(UTC)
        async with self._pool.acquire() as conn, conn.transaction():
            # Ensure a row exists, then lock it.  The INSERT ... ON CONFLICT
            # DO NOTHING + SELECT FOR UPDATE pattern avoids lost updates
            # when two replicas race on the first violation for a user.
            await conn.execute(
                """INSERT INTO sentinel_strikes (user_id, org_id)
                   VALUES ($1, $2)
                   ON CONFLICT (user_id) DO NOTHING""",
                user_id,
                org_id,
            )
            row = await conn.fetchrow(
                "SELECT * FROM sentinel_strikes WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            assert row is not None  # just inserted or already existed

            new_count: int = int(row["strike_count"]) + 1
            scrutiny = str(row["scrutiny_level"])
            locked_until = row["locked_until"]
            disabled = bool(row["disabled"])

            if new_count >= 3:
                scrutiny = DISABLED
                disabled = True
                logger.warning(
                    "ACCOUNT DISABLED: user=%s org=%s strikes=%d",
                    user_id,
                    org_id,
                    new_count,
                )
            elif new_count == 2:
                scrutiny = LOCKED
                locked_until = now + LOCKOUT_DURATION
                logger.warning(
                    "ACCOUNT LOCKED: user=%s org=%s until=%s",
                    user_id,
                    org_id,
                    locked_until.isoformat(),
                )
            elif new_count == 1:
                scrutiny = ELEVATED
                logger.warning(
                    "STRIKE 1: user=%s org=%s -- elevated scrutiny enabled",
                    user_id,
                    org_id,
                )

            updated = await conn.fetchrow(
                """UPDATE sentinel_strikes SET
                     strike_count = $2,
                     scrutiny_level = $3,
                     locked_until = $4,
                     disabled = $5,
                     last_violation_at = $6,
                     updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                new_count,
                scrutiny,
                locked_until,
                disabled,
                now,
            )
            await conn.execute(
                """INSERT INTO sentinel_strike_violations
                     (user_id, org_id, timestamp, flags, boundary, detail)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                user_id,
                org_id,
                now,
                list(flags),
                boundary,
                detail,
            )
            violations = await conn.fetch(
                """SELECT timestamp, flags, boundary, detail
                   FROM sentinel_strike_violations
                   WHERE user_id = $1
                   ORDER BY id ASC""",
                user_id,
            )

        assert updated is not None
        return _row_to_record(updated, violations)

    async def submit_appeal(self, user_id: str, appeal_text: str) -> bool:
        """Submit an appeal for a strike.  Returns True if recorded."""
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT strike_count FROM sentinel_strikes WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if row is None or int(row["strike_count"]) == 0:
                return False
            await conn.execute(
                """UPDATE sentinel_strikes SET
                     last_appeal = $2,
                     last_appeal_at = NOW(),
                     updated_at = NOW()
                   WHERE user_id = $1""",
                user_id,
                appeal_text,
            )
        logger.info("Appeal submitted: user=%s text=%s", user_id, appeal_text[:100])
        return True

    async def remove_strikes(
        self,
        user_id: str,
        count: int | None = None,
    ) -> StrikeRecord | None:
        """Remove strikes from a user.  ``count=None`` clears all.

        Called by admins.  Recalculates scrutiny level from the new count
        using the same rules as :meth:`InMemoryStrikeTracker._recalculate_level`.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM sentinel_strikes WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if row is None:
                return None

            current = int(row["strike_count"])
            new_count = 0 if count is None else max(0, current - count)
            scrutiny, disabled, locked_until = _recalculate_level(
                new_count,
                current_locked_until=row["locked_until"],
            )

            updated = await conn.fetchrow(
                """UPDATE sentinel_strikes SET
                     strike_count = $2,
                     scrutiny_level = $3,
                     locked_until = $4,
                     disabled = $5,
                     updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                new_count,
                scrutiny,
                locked_until,
                disabled,
            )
            violations = await conn.fetch(
                """SELECT timestamp, flags, boundary, detail
                   FROM sentinel_strike_violations
                   WHERE user_id = $1
                   ORDER BY id ASC""",
                user_id,
            )

        assert updated is not None
        logger.info(
            "Strikes removed: user=%s new_count=%d level=%s",
            user_id,
            new_count,
            scrutiny,
        )
        return _row_to_record(updated, violations)

    async def unlock(self, user_id: str) -> StrikeRecord | None:
        """Unlock a locked account (team_admin+ action).

        Clears ``locked_until`` but does NOT remove strikes.  If the account
        is still disabled, scrutiny stays at DISABLED (admin must call
        :meth:`enable` to re-enable).
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM sentinel_strikes WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if row is None:
                return None

            disabled = bool(row["disabled"])
            strike_count = int(row["strike_count"])
            scrutiny = str(row["scrutiny_level"])
            if not disabled:
                scrutiny = ELEVATED if strike_count >= 1 else NORMAL

            updated = await conn.fetchrow(
                """UPDATE sentinel_strikes SET
                     locked_until = NULL,
                     scrutiny_level = $2,
                     updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                scrutiny,
            )
            violations = await conn.fetch(
                """SELECT timestamp, flags, boundary, detail
                   FROM sentinel_strike_violations
                   WHERE user_id = $1
                   ORDER BY id ASC""",
                user_id,
            )

        assert updated is not None
        logger.info("Account unlocked: user=%s", user_id)
        return _row_to_record(updated, violations)

    async def enable(self, user_id: str) -> StrikeRecord | None:
        """Re-enable a disabled account (org_admin+ action).

        Clears ``disabled`` and ``locked_until`` but does NOT remove strikes.
        Scrutiny falls back to ELEVATED if any strikes remain, else NORMAL.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM sentinel_strikes WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if row is None:
                return None

            strike_count = int(row["strike_count"])
            scrutiny = ELEVATED if strike_count >= 1 else NORMAL

            updated = await conn.fetchrow(
                """UPDATE sentinel_strikes SET
                     disabled = FALSE,
                     locked_until = NULL,
                     scrutiny_level = $2,
                     updated_at = NOW()
                   WHERE user_id = $1
                   RETURNING *""",
                user_id,
                scrutiny,
            )
            violations = await conn.fetch(
                """SELECT timestamp, flags, boundary, detail
                   FROM sentinel_strike_violations
                   WHERE user_id = $1
                   ORDER BY id ASC""",
                user_id,
            )

        assert updated is not None
        logger.info("Account re-enabled: user=%s", user_id)
        return _row_to_record(updated, violations)


# ---------------------------------------------------------------------- helpers


def _recalculate_level(
    new_count: int,
    *,
    current_locked_until: datetime | None,
) -> tuple[str, bool, datetime | None]:
    """Recalculate (scrutiny_level, disabled, locked_until) from strike count.

    Mirrors :meth:`InMemoryStrikeTracker._recalculate_level` exactly:

    * 3+  -> DISABLED, disabled=True, locked_until preserved
    * 2   -> LOCKED, disabled unchanged, locked_until preserved
            (admin may have unlocked; we never re-lock here)
    * 1   -> ELEVATED, disabled=False, locked_until=None
    * 0   -> NORMAL,   disabled=False, locked_until=None
    """
    if new_count >= 3:
        return DISABLED, True, current_locked_until
    if new_count == 2:
        # Do not re-lock if admin already unlocked -- preserve current value.
        return LOCKED, False, current_locked_until
    if new_count >= 1:
        return ELEVATED, False, None
    return NORMAL, False, None


def _row_to_record(
    row: asyncpg.Record,
    violation_rows: list[asyncpg.Record],
) -> StrikeRecord:
    """Convert a ``sentinel_strikes`` row (+ its violations) to StrikeRecord."""
    record = StrikeRecord(
        user_id=str(row["user_id"]),
        org_id=str(row["org_id"]),
        strike_count=int(row["strike_count"]),
        scrutiny_level=str(row["scrutiny_level"]),
        locked_until=row["locked_until"],
        disabled=bool(row["disabled"]),
        last_violation_at=row["last_violation_at"],
        last_appeal=str(row["last_appeal"]),
        last_appeal_at=row["last_appeal_at"],
    )
    record.violations = [
        ViolationRecord(
            timestamp=vrow["timestamp"],
            flags=tuple(vrow["flags"]),
            boundary=str(vrow["boundary"]),
            detail=str(vrow["detail"]),
        )
        for vrow in violation_rows
    ]
    return record
