-- Stronghold 012: Persistent strike tracker (PR-4, BACKLOG R22)
-- Replaces InMemoryStrikeTracker state with postgres-backed tables so strike
-- state survives process restart and stays consistent across multi-replica
-- Stronghold-API deployments.
--
-- Two tables:
--   sentinel_strikes            -- per-user strike record (1 row per user_id)
--   sentinel_strike_violations  -- append-only per-violation history
--
-- The schema mirrors the dataclass fields in
-- src/stronghold/security/strikes.py (StrikeRecord + ViolationRecord) so the
-- PostgresStrikeTracker and InMemoryStrikeTracker share an identical contract.

-- ============================================================================
-- sentinel_strikes: per-user strike state
-- ============================================================================

CREATE TABLE IF NOT EXISTS sentinel_strikes (
    user_id            TEXT PRIMARY KEY,
    org_id             TEXT NOT NULL,
    strike_count       INTEGER NOT NULL DEFAULT 0,
    scrutiny_level     TEXT NOT NULL DEFAULT 'normal',
    locked_until       TIMESTAMPTZ,
    disabled           BOOLEAN NOT NULL DEFAULT FALSE,
    last_violation_at  TIMESTAMPTZ,
    last_appeal        TEXT NOT NULL DEFAULT '',
    last_appeal_at     TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sentinel_strikes_org
    ON sentinel_strikes (org_id);

CREATE INDEX IF NOT EXISTS idx_sentinel_strikes_disabled
    ON sentinel_strikes (org_id, disabled)
    WHERE disabled = TRUE;

-- ============================================================================
-- sentinel_strike_violations: append-only violation history
-- ============================================================================

CREATE TABLE IF NOT EXISTS sentinel_strike_violations (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    org_id      TEXT NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    flags       TEXT[] NOT NULL DEFAULT '{}',
    boundary    TEXT NOT NULL DEFAULT 'user_input',
    detail      TEXT NOT NULL DEFAULT '',
    CONSTRAINT fk_sentinel_strike_violations_user
        FOREIGN KEY (user_id)
        REFERENCES sentinel_strikes (user_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sentinel_strike_violations_user
    ON sentinel_strike_violations (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_sentinel_strike_violations_org
    ON sentinel_strike_violations (org_id, timestamp DESC);
