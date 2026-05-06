-- Persistence for the Emissary MCP gateway plane.
--
-- Four tables, one per long-lived component:
--
--   mcp_tool_catalog        — approved tool entries (composite PK over
--                              fingerprint_value + approved_at_scope so the
--                              same fingerprint can be approved at multiple
--                              scopes simultaneously).
--   mcp_emissary_backends   — backend registrations (one per fingerprint;
--                              fingerprint is the natural primary key).
--   mcp_keyward_revocations — revoked token ids. Short-lived rows; a
--                              periodic cleanup task should drop entries
--                              older than the longest-known token TTL.
--   mcp_composer_definitions — composite tool step graphs (one per
--                              fingerprint).
--
-- All JSON-shaped fields use JSONB for queryability and atomic updates.
--
-- Idempotency cache and Emissary sessions are intentionally NOT in this
-- migration — they belong in Redis (high write volume, short TTL,
-- multi-replica session affinity is a separate design concern).

CREATE TABLE IF NOT EXISTS mcp_tool_catalog (
    fingerprint_value   TEXT        NOT NULL,
    approved_at_scope   TEXT        NOT NULL,
    name                TEXT        NOT NULL,
    schema_hash         TEXT        NOT NULL,
    trust_tier          TEXT        NOT NULL,
    provenance          TEXT        NOT NULL,
    org_id              TEXT        NOT NULL DEFAULT '',
    team_id             TEXT        NOT NULL DEFAULT '',
    user_id             TEXT        NOT NULL DEFAULT '',
    allowed_audiences   JSONB       NOT NULL,
    declared_caps       JSONB       NOT NULL,
    approved_at         TIMESTAMPTZ NOT NULL,
    approved_by         TEXT        NOT NULL DEFAULT '',
    expires_at          TIMESTAMPTZ NULL,
    PRIMARY KEY (fingerprint_value, approved_at_scope)
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_catalog_name ON mcp_tool_catalog (name);
CREATE INDEX IF NOT EXISTS idx_mcp_tool_catalog_org ON mcp_tool_catalog (org_id) WHERE org_id <> '';

CREATE TABLE IF NOT EXISTS mcp_emissary_backends (
    fingerprint_value   TEXT        PRIMARY KEY,
    name                TEXT        NOT NULL,
    target_kind         TEXT        NOT NULL,
    audiences           JSONB       NOT NULL,
    session_affinity    BOOLEAN     NOT NULL DEFAULT FALSE,
    metadata            JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS mcp_keyward_revocations (
    token_id            TEXT        PRIMARY KEY,
    revoked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason              TEXT        NOT NULL DEFAULT '',
    -- Optional context preserved for audit when revocation criteria carried
    -- something other than a token_id (revoke-by-tool, revoke-by-user, etc.).
    -- Each row still represents a single concretely-revoked token id.
    revoked_by_tool_fp  TEXT        NULL,
    revoked_by_user_id  TEXT        NULL,
    revoked_by_audience TEXT        NULL
);

CREATE INDEX IF NOT EXISTS idx_mcp_keyward_revocations_revoked_at
    ON mcp_keyward_revocations (revoked_at);

CREATE TABLE IF NOT EXISTS mcp_composer_definitions (
    fingerprint_value   TEXT        PRIMARY KEY,
    name                TEXT        NOT NULL,
    description         TEXT        NOT NULL DEFAULT '',
    schema_hash         TEXT        NOT NULL,
    input_schema        JSONB       NOT NULL,
    output_schema       JSONB       NOT NULL,
    steps               JSONB       NOT NULL,
    trust_tier          TEXT        NOT NULL
);
