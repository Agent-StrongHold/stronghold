# 02 — Document Model

**Status**: P0 / Foundation. Replaces today's session-scoped `Canvas`.
**One-liner**: a `Document` owns N ordered `Page`s, each with its own print spec
and ordered `Layer`s, all tenant-scoped and persisted.

## Problem it solves

Today `_canvases: dict[str, Canvas]` is in-process and single-page. A book has
≥32 pages, must survive restarts, and must be tenant-isolated. A poster is one
page but still needs persistence. An infographic is one page but may have
multiple "tabs" (e.g. summary + detail variants).

## Data model

```
Document (frozen):
  id: str                          # uuid
  tenant_id: str
  owner_id: str
  name: str
  kind: DocumentKind               # picture_book | early_reader | poster | infographic | freeform
  pages: tuple[Page, ...]
  master_pages: tuple[Page, ...]   # reusable, referenced by Page.master_id
  brand_kit_id: str | None
  style_lock_id: str | None
  created_at: datetime
  updated_at: datetime
  archived: bool = False
  metadata: Mapping[str, Any]      # arbitrary, e.g. ISBN, copyright, age_band
```

```
Page (frozen):
  id: str
  ordering: int                    # 0-based; verso (left) = even, recto (right) = odd
  name: str = ""                   # "title", "dedication", "spread-1", "back-cover"
  print_spec: PrintSpec
  background: Color = "#FFFFFF"
  master_id: str | None
  layers: tuple[Layer, ...]        # back-to-front by z_index, ties by ordering
```

```
PrintSpec (frozen):
  trim_size: tuple[int, int]       # pixels at target DPI
  dpi: int = 300
  bleed: int = 38                  # pixels = 0.125" @ 300 DPI
  safe_area: int = 75              # pixels = 0.25" @ 300 DPI
  color_mode: ColorMode = sRGB     # sRGB | CMYK
  icc_profile: str | None = None   # for CMYK output
```

DocumentKind enum and PrintSpec are detailed in [08-print-spec.md](08-print-spec.md).

## Persistence schema

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  owner_id UUID NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  brand_kit_id UUID REFERENCES brand_kits(id),
  style_lock_id UUID REFERENCES style_locks(id),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  archived BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX documents_tenant_owner_idx ON documents (tenant_id, owner_id);
CREATE INDEX documents_kind_idx ON documents (tenant_id, kind);

CREATE TABLE pages (
  id UUID PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  ordering INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  is_master BOOLEAN NOT NULL DEFAULT FALSE,
  master_id UUID REFERENCES pages(id),
  print_spec JSONB NOT NULL,
  background TEXT NOT NULL DEFAULT '#FFFFFF',
  UNIQUE (document_id, ordering, is_master)
);

CREATE TABLE layers (
  id UUID PRIMARY KEY,
  page_id UUID NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  z_index INTEGER NOT NULL,
  ordering INTEGER NOT NULL,         -- tie-break for equal z_index
  layer_type TEXT NOT NULL,
  source JSONB NOT NULL,             -- raster blob refs, vector geometry, text content
  effects JSONB NOT NULL DEFAULT '[]'::jsonb,
  mask_blob_id UUID REFERENCES blobs(id),
  blend_mode TEXT NOT NULL DEFAULT 'normal',
  opacity REAL NOT NULL DEFAULT 1.0,
  x INTEGER NOT NULL DEFAULT 0,
  y INTEGER NOT NULL DEFAULT 0,
  scale REAL NOT NULL DEFAULT 1.0,
  rotation REAL NOT NULL DEFAULT 0.0,
  visible BOOLEAN NOT NULL DEFAULT TRUE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX layers_page_z_idx ON layers (page_id, z_index, ordering);

CREATE TABLE blobs (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  content_type TEXT NOT NULL,
  byte_size BIGINT NOT NULL,
  storage_url TEXT NOT NULL,         -- s3://... or local path
  sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, sha256)         -- dedupe per tenant
);
```

Raster `image_bytes` are stored in object storage (S3-compatible), referenced
from `layers.source` JSON via `blob_id`. Pages and Layers are immutable; "edit"
creates a new row + updates document's `updated_at`. History is implicit in
this append model (see §04 of overview for snapshots, P2).

## API surface (canvas tool actions)

Existing actions (`generate`, `refine`, etc.) already operate on a session
canvas. New actions for document scope:

| Action | Args | Effect |
|---|---|---|
| `document_create` | `kind, name, page_specs: tuple[PrintSpec, ...]` | New Document with N empty pages |
| `document_open` | `document_id` | Load into session |
| `document_save` | (auto-save also on every mutation) | Flush to DB |
| `document_archive` | `document_id` | Soft-delete |
| `page_add` | `document_id, ordering, print_spec, [master_id]` | Insert page |
| `page_delete` | `page_id` | Remove + reorder |
| `page_reorder` | `document_id, ordering: tuple[str, ...]` | New page order |
| `page_duplicate` | `page_id, [target_ordering]` | Deep-copy page |
| `master_create` | `document_id, name, print_spec` | New master page |
| `master_apply` | `page_id, master_id` | Set page's master_id |

## Edge cases

1. **Concurrent edits to same document** — last-write-wins on Page; Layer
   mutations carry an `expected_version` and fail with `ConcurrentEditError` on
   mismatch (P1; for P0 single-author is assumed).
2. **Page reorder breaks bookmarks/master refs** — `master_id` references by
   master page UUID, not ordering, so reordering is safe.
3. **Master page deleted while a Page references it** — block deletion; require
   `master_apply` to a different (or null) master first.
4. **Document with 0 pages** — allowed (empty draft); export rejects with
   `EmptyDocumentError`.
5. **Tenant boundary leak** — every read query filters by `tenant_id`; tested
   per integration suite.
6. **Verso/recto orientation in books** — `Page.ordering` parity drives bind
   margin in master pages; doc kind `picture_book` enforces even count.
7. **Layer ordering ties** — `(z_index, ordering)` tuple; ordering bumps on
   duplicate to keep deterministic stacking.
8. **Blob dedupe across tenants** — UNIQUE on `(tenant_id, sha256)` only;
   never deduplicate across tenants (would leak existence).

## Errors

- `DocumentNotFoundError(StrongholdError, code="DOCUMENT_NOT_FOUND")`
- `EmptyDocumentError(StrongholdError, code="EMPTY_DOCUMENT")`
- `ConcurrentEditError(StrongholdError, code="CONCURRENT_EDIT")`
- `MasterInUseError(StrongholdError, code="MASTER_IN_USE")`
- `InvalidPageOrderingError(ConfigError, code="INVALID_PAGE_ORDERING")`

## Test surface

- Unit: Document/Page/Layer frozen invariants; PrintSpec defaults; ordering
  uniqueness; UUID validation.
- Integration: tenant-scoped CRUD round-trip; concurrent edit detection;
  page reorder preserves master refs; blob dedupe within tenant only.
- Security: cross-tenant read returns 0 rows even with valid document_id;
  Bandit clean (no SQL string concat).
- Migration: forward + backward Alembic test on a populated test DB.

## Dependencies

- existing Postgres + asyncpg
- Alembic migrations (existing pattern in `migrations/`)
- S3-compatible blob store (existing `persistence/` layer)
