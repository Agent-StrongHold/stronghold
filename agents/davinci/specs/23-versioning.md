# 23 — Versioning & History

**Status**: P0 / Trust phase. Required for safe destructive actions.
**One-liner**: every Document mutation appends an immutable version; every
session can undo/redo, and named checkpoints protect risky regenerations.

## Problem it solves

A non-technical user must trust that experiments don't lose work. The agent
generates → user accepts 90% → user tweaks → agent regenerates a layer →
suddenly the page looks worse. Without history, that regression is permanent.
With versioning, every change is a snapshot the user can return to.

## Data model

```
DocumentVersion (frozen):
  id: str                          # uuid; monotonically time-sortable (ULID)
  document_id: str
  parent_version_id: str | None    # the version this descended from
  author_id: str                   # user or "agent:davinci"
  author_kind: AuthorKind          # USER | AGENT | SYSTEM
  ordinal: int                     # 1-indexed within document
  created_at: datetime
  delta: VersionDelta              # what changed
  snapshot_blob_id: str | None     # full Document JSON if checkpoint, else null
  message: str = ""                # auto-generated or user-provided

VersionDelta (frozen):
  ops: tuple[VersionOp, ...]
  affected_page_ids: tuple[str, ...]
  affected_layer_ids: tuple[str, ...]

VersionOp (tagged union, frozen):
  PageAdded:        {kind: "page_added", page_id, ordering, snapshot}
  PageDeleted:      {kind: "page_deleted", page_id, ordering, prior_snapshot}
  PageReordered:    {kind: "page_reordered", before, after}
  LayerAdded:       {kind: "layer_added", layer_id, page_id, snapshot}
  LayerUpdated:     {kind: "layer_updated", layer_id, before, after}  # JSON Patch
  LayerDeleted:     {kind: "layer_deleted", layer_id, prior_snapshot}
  EffectChanged:    {kind: "effect_changed", layer_id, before_effects, after_effects}
  DocumentMetaChanged: {kind: "doc_meta_changed", before, after}

AuthorKind (StrEnum):
  USER
  AGENT
  SYSTEM
```

## Snapshot strategy

Two storage layers:
- **Delta-only versions** for normal operations — small, compact JSON Patch.
- **Snapshot versions** every N ops (default 25) OR on `checkpoint` request —
  full Document blob for fast restore.
- Restore at version V = nearest snapshot ≤ V + apply forward deltas.

This bounds restore cost to O(N) where N = snapshot interval, regardless of
total history length.

## Branching

Versions form a DAG. Default is linear (each new version's parent = HEAD).
Branching cases:
- User reverts to an old version → new versions descend from that old version,
  HEAD moves to the new branch.
- The original branch is preserved (not deleted) and reachable via UI history.

No merge support in P0 (single-author). Branches are visible but additive.

## Checkpoints

Named, user-initiated snapshots:

| Checkpoint event | Trigger |
|---|---|
| Manual | UI "checkpoint" button or chat command |
| Pre-regen | Before any inpaint/outpaint/upscale/refine |
| Pre-template-apply | Before `template_apply` mutates many layers |
| Pre-LoRA-apply | Before applying a fine-tune to existing pages |
| Pre-export | Before any export action (so user can revert if export reveals issues) |

## API surface

| Action | Args | Returns |
|---|---|---|
| `version_list` | `document_id, [limit, before, after]` | paginated DocumentVersion list |
| `version_get` | `document_id, version_id` | full restored Document state |
| `version_diff` | `document_id, from_version, to_version` | structured diff |
| `version_revert` | `document_id, version_id` | new HEAD pointing at restored state |
| `checkpoint_create` | `document_id, name, message` | DocumentVersion with snapshot |
| `version_compare_render` | `document_id, version_a, version_b, page_id` | side-by-side rendered image |

## Retention policy

- Versions retained: 90 days OR last 200, whichever is greater
- Checkpoint versions: forever (until document deleted)
- User can pin specific versions to retain
- Document deletion archives history with the document; full delete removes both

## Edge cases

1. **Long undo chain across snapshot boundary** — restore stitches snapshot +
   forward deltas; tested for correctness vs. naive replay.
2. **Concurrent versions from agent + user** — append-only, both succeed,
   ordinals interleave; ConcurrentEditError only on optimistic locking writes.
3. **Revert to a version with deleted blobs** — blobs are reference-counted;
   blob deletion is deferred until no version references it.
4. **Revert past a deleted master page** — restore re-creates the master page
   from snapshot.
5. **Storage explosion** (every effect_toggle creates a version) — coalesce
   adjacent same-author same-layer ops within 5s into one version with
   combined delta.
6. **Agent-authored vs user-authored versions** — both stored; UI filters by
   author. Important for the corrections pipeline (§19) which only learns
   from user-authored deltas applied AFTER agent-authored ones.
7. **Restore of an LLM-generated layer** — the original gen prompt is preserved
   in the layer's metadata; restore re-attaches it. Re-running the gen would
   produce different bytes; the snapshot wins.
8. **PII in messages** — version `message` field may contain user input;
   tenant-scoped; included in deletion sweeps.

## Errors

- `VersionNotFoundError(StrongholdError, code="VERSION_NOT_FOUND")`
- `VersionTooOldError(StrongholdError, code="VERSION_RETIRED")` — beyond
  retention
- `RevertConflictError(StrongholdError, code="REVERT_CONFLICT")` — branching
  ambiguity that requires operator decision

## Test surface

- Unit: ULID monotonicity; delta application is deterministic; snapshot
  intervals correct.
- Integration: 1000-op history, restore to op 500, output matches recompute;
  branching produces correct DAG; coalescing works.
- Property (hypothesis): for any sequence of ops, restore-to-final = apply-all
  byte-identical; replay from any snapshot equals replay from start.
- Security: cross-tenant version_get returns nothing.
- Performance (`@perf`): restore from 1k-op history < 500 ms with 25-op
  snapshots.

## Dependencies

- ULID library (small, pure-Python)
- JSON Patch (RFC 6902, library `jsonpatch`)
- existing Postgres + S3-compat blob store
