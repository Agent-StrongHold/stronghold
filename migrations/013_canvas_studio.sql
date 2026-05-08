-- Migration 013: Canvas Studio tables (spec 1189)
--
-- Creates four tables:
--   canvases          — canvas workspaces
--   layers            — individual image layers per canvas
--   generation_jobs   — async generation job records
--   composite_records — composite snapshots per canvas

-- ── canvases ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS canvases (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    width            INTEGER NOT NULL CHECK (width >= 64 AND width <= 8192 AND width % 8 = 0),
    height           INTEGER NOT NULL CHECK (height >= 64 AND height <= 8192 AND height % 8 = 0),
    background_color TEXT NOT NULL DEFAULT '#FFFFFF',
    org_id           TEXT NOT NULL DEFAULT '',
    layer_count      INTEGER NOT NULL DEFAULT 0 CHECK (layer_count >= 0),
    archived_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_canvases_org_id       ON canvases (org_id);
CREATE INDEX IF NOT EXISTS idx_canvases_updated_at   ON canvases (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_canvases_archived_at  ON canvases (archived_at)
    WHERE archived_at IS NOT NULL;

-- ── layers ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS layers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_id        UUID NOT NULL REFERENCES canvases (id) ON DELETE RESTRICT,
    name             TEXT NOT NULL,
    layer_type       TEXT NOT NULL DEFAULT 'background',
    z_index          INTEGER NOT NULL DEFAULT 0 CHECK (z_index >= 0),
    x                DOUBLE PRECISION NOT NULL DEFAULT 0,
    y                DOUBLE PRECISION NOT NULL DEFAULT 0,
    scale            DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (scale > 0),
    rotation         DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (rotation >= 0 AND rotation < 360),
    opacity          DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (opacity >= 0 AND opacity <= 1),
    blend_mode       TEXT NOT NULL DEFAULT 'normal',
    visible          BOOLEAN NOT NULL DEFAULT TRUE,
    locked           BOOLEAN NOT NULL DEFAULT FALSE,
    image_path       TEXT,
    prompt           TEXT,
    negative_prompt  TEXT,
    model_id         TEXT,
    tier             TEXT NOT NULL DEFAULT 'draft',
    generation_seed  INTEGER,
    text_config      JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Enforces the z_index uniqueness invariant at the database level
    CONSTRAINT layers_canvas_z_index_unique UNIQUE (canvas_id, z_index)
);

CREATE INDEX IF NOT EXISTS idx_layers_canvas_id  ON layers (canvas_id, z_index);
CREATE INDEX IF NOT EXISTS idx_layers_updated_at ON layers (updated_at DESC);

-- ── generation_jobs ────────────────────────────────────────────────���──

CREATE TABLE IF NOT EXISTS generation_jobs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    layer_id         UUID NOT NULL REFERENCES layers (id) ON DELETE CASCADE,
    canvas_id        UUID NOT NULL REFERENCES canvases (id) ON DELETE CASCADE,
    action           TEXT NOT NULL DEFAULT 'generate',
    status           TEXT NOT NULL DEFAULT 'pending',
    model_id         TEXT NOT NULL DEFAULT '',
    prompt           TEXT NOT NULL DEFAULT '',
    params           JSONB NOT NULL DEFAULT '{}',
    result_paths     JSONB NOT NULL DEFAULT '[]',
    selected_index   INTEGER,
    error_message    TEXT,
    started_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_layer_id_status
    ON generation_jobs (layer_id, status)
    WHERE status IN ('pending', 'running');

CREATE INDEX IF NOT EXISTS idx_jobs_canvas_id ON generation_jobs (canvas_id);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON generation_jobs (created_at DESC);

-- ── composite_records ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS composite_records (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canvas_id        UUID NOT NULL REFERENCES canvases (id) ON DELETE CASCADE,
    image_bytes      BYTEA NOT NULL,
    width            INTEGER NOT NULL,
    height           INTEGER NOT NULL,
    layer_snapshot   JSONB NOT NULL DEFAULT '[]',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_composites_canvas_id_created
    ON composite_records (canvas_id, created_at DESC);
