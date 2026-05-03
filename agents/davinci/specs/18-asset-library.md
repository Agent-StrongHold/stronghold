# 18 — Asset Library

**Status**: P0 / Document phase. Unifies characters, props, uploads.
**One-liner**: a tenant-scoped library of reusable visual assets — characters,
props, uploads — searchable by tag and embedding, drag-onto-canvas.

## Problem it solves

Building a children's book consistently means reusing visual elements: the
same character on 30 pages, the same dragon prop in three scenes, the same
uploaded logo on every page. The existing canvas tool supports
`save_reference` for character refs only. This spec unifies all reusable
visual assets under one library with consistent search, tagging, and
applicability.

## Asset kinds

```
AssetKind (StrEnum):
  CHARACTER          # person/animal with persisted reference sheets
  PROP               # generated object (dragon, chest, throne) with isolation alpha
  UPLOAD             # user-imported PNG/SVG/JPG (logos, photos, hand-drawn art)
  TEMPLATE_THUMB     # template thumbnails (private read-only)
```

## Data model

```
Asset (frozen):
  id: str
  tenant_id: str
  owner_id: str
  kind: AssetKind
  name: str
  description: str = ""
  tags: tuple[str, ...]
  thumbnail_blob_id: str
  primary_blob_id: str             # the canonical image
  reference_sheet_blob_ids: tuple[str, ...] = ()  # multi-view variants
  embedding: tuple[float, ...] | None    # CLIP, for semantic search
  metadata: Mapping[str, Any]      # generation prompt, model, age band, etc.
  trust_tier: TrustTier            # T0 builtin, T2 admin, T3 user, T4 community
  provenance: Provenance
  uses_count: int = 0
  created_at, updated_at

CharacterAsset(Asset):
  age_band: AgeBand | None
  visual_traits: Mapping[str, str]  # hair, eyes, build, age, etc.
  multi_view: tuple[CharacterView, ...]   # front, side, back, expressions

PropAsset(Asset):
  category: PropCategory             # FURNITURE | NATURE | TOY | ANIMAL_OBJECT |
                                     # WEAPON | TOOL | FOOD | DECOR | OTHER
  isolation_alpha: bool = True       # has transparent background
  multi_angle: tuple[ImageRef, ...] = ()
  scale_hint: float = 1.0            # relative size suggestion

UploadAsset(Asset):
  source_kind: UploadSourceKind      # PHOTO | LOGO | ILLUSTRATION | SVG | OTHER
  rights_acknowledged: bool          # user attests they have rights
  warden_verdict_id: str             # Warden scan record
```

## Storage

Same blob store as documents. Embeddings stored in pgvector or similar:

```sql
CREATE TABLE assets (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  owner_id UUID NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  tags TEXT[] NOT NULL DEFAULT '{}',
  thumbnail_blob_id UUID,
  primary_blob_id UUID NOT NULL REFERENCES blobs(id),
  embedding VECTOR(512),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  trust_tier TEXT NOT NULL DEFAULT 't3',
  provenance TEXT NOT NULL DEFAULT 'user',
  uses_count INTEGER NOT NULL DEFAULT 0,
  archived BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX assets_tenant_kind_idx ON assets (tenant_id, kind);
CREATE INDEX assets_tags_idx ON assets USING gin (tags);
CREATE INDEX assets_embedding_idx ON assets USING hnsw (embedding vector_cosine_ops);
```

## Search

Three modes:

1. **Tag** — boolean over tag array
2. **Substring** — `name ILIKE '%text%'` + description
3. **Semantic** — CLIP embedding cosine; "find that dragon I made last week"

Search is always tenant-scoped. UI surfaces the three modes; query auto-routes
based on input style.

## Drag-onto-canvas

Asset → new Layer:
- CHARACTER, PROP → raster Layer with `source.image_bytes` from primary blob;
  multi-view sheet stored in `metadata.reference_sheet` for use in subsequent
  generative calls
- UPLOAD (raster) → raster Layer
- UPLOAD (SVG) → shape Layer of kind PATH with parsed geometry

Insertion location: at user-clicked point or page centre; default scale
preserves aspect; z_index = top.

## Asset creation paths

| Source | Action |
|---|---|
| Existing canvas layer | `asset_save_from_layer(layer_id, kind, name, tags)` |
| Generative request | `generate(...) → asset_save(name, tags)` |
| Multi-view from reference sheet | `asset_save_with_views(layer_id, sheet_layer_id)` |
| Upload | `asset_upload(file_bytes, kind, name, tags, rights_acknowledged=True)` |
| Promote prior `save_reference` | one-time migration on rollout |

## Embedding generation

CLIP image embeddings via Replicate or local ONNX model:

```
def embed(image_bytes) -> tuple[float, ...]:
    # CLIP ViT-B/32 — 512-dim, ~30ms on CPU
    return clip_image(image_bytes)
```

Embeddings computed at asset creation; re-computed on primary blob change.

## API surface

| Action | Args | Returns |
|---|---|---|
| `asset_list` | `[kind, tags, owner_only]` | tuple[Asset summaries] |
| `asset_get` | `asset_id` | Asset |
| `asset_search` | `query, [kind, tags, mode: tag\|substring\|semantic]` | ranked Asset list |
| `asset_save_from_layer` | `layer_id, kind, name, [tags]` | Asset |
| `asset_save_with_views` | `layer_id, sheet_layer_id, name, [tags]` | CharacterAsset |
| `asset_upload` | `file_bytes, kind, name, [tags]` | Asset |
| `asset_insert` | `asset_id, page_id, [position, scale]` | new Layer |
| `asset_update` | `asset_id, name?, description?, tags?` | Asset |
| `asset_archive` | `asset_id` | (soft delete) |

## Asset versioning + character ref evolution

When the corrections pipeline (§19) refines a character ("rounder eyes"), the
asset's primary blob updates AND a new version is recorded. Existing pages
that reference the asset:
- Default: keep their copy (frozen at use-time blob)
- Per-doc setting `auto_update_assets: bool = false`: re-link to latest

This avoids unintentionally rewriting old books when a character evolves.

## Edge cases

1. **Character with multi-view sheet has views misaligned** — let the user
   specify per-view bbox in the sheet; auto-detect via face/centroid for
   simple cases.
2. **Prop with isolation_alpha=true but raster has no alpha** — auto-generate
   alpha via rembg (§03 mask system).
3. **Upload of copyrighted/trademarked image** — Warden + Sentinel may flag;
   user must acknowledge rights; storing flagged uploads requires explicit
   override (logged).
4. **SVG upload with embedded JS** — strip script elements; reject if SVG
   relies on them.
5. **Embedding model unavailable** — asset created without embedding;
   semantic search omits it; embedding back-filled when model returns.
6. **Asset name collision** — allow duplicates within tenant; surface
   warning in UI; agent disambiguates by id.
7. **Cross-tenant asset link in a shared template** — template carries copy
   of asset bytes; template apply re-creates the asset in target tenant.
8. **Asset deleted while in use by N documents** — block hard-delete; offer
   soft-archive with "X documents reference this".
9. **Prop scale_hint mismatched in real composite** — scale_hint is advisory;
   layer is freely scalable.
10. **Bulk archive** — tag-based; tenant audit log for batch ops.

## Errors

- `AssetNotFoundError`
- `AssetUploadValidationError(SecurityError)` — Warden / Sentinel rejection
- `AssetReferenceInUseError(ConfigError)` — hard-delete blocked
- `EmbeddingUnavailableError(RoutingError)` — non-fatal, downgraded

## Test surface

- Unit: every AssetKind constructs valid; Tag normalization (lowercase,
  slugified); embedding dim = 512.
- Integration: round-trip create → search → insert → use; tenant isolation;
  CLIP embedding fixture matches expected nearest neighbours; SVG sanitizer
  strips script.
- Security: cross-tenant asset_get → not found; upload Warden scan; bandit
  clean.
- Performance: semantic search over 10k assets < 100ms (HNSW index).

## Dependencies

- §02 document, §03 mask system (for isolation_alpha), §17 template authoring,
  CLIP model (Replicate / local ONNX)
- pgvector for embedding index
- existing Postgres + S3-compat blob store
