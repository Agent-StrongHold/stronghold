# 19 — Corrections (Capture)

**Status**: P0 / Hyperagent phase. The signal source.
**One-liner**: every direct-manipulation edit and every "actually, change…"
chat ask emits a structured `Correction` event capturing what the agent
proposed vs what the user kept.

## Problem it solves

The user's 10% tweaks are the highest-quality training signal Da Vinci
will ever see. Without structured capture, that signal evaporates. With
it, the corrections feed §20 learning aggregation and §21 LoRA training.

## Data model

```
Correction (frozen):
  id: str                          # uuid; ULID-sortable
  tenant_id: str
  user_id: str
  document_id: str
  page_id: str
  layer_id: str | None             # null for page-/document-scope corrections
  session_id: str
  kind: CorrectionKind
  before: LayerSnapshot | PageSnapshot
  after: LayerSnapshot | PageSnapshot
  source: CorrectionSource         # DIRECT_MANIP | CHAT | AUTO_FIX
  inferred_intent: str             # vision/diff-LLM extracted
  context: CorrectionContext       # surrounding state
  signal_strength: float           # 0..1; computed at aggregation time
  reverted: bool = False           # set true if undone within 60s
  reverted_at: datetime | None
  timestamp: datetime              # wall-clock at capture
  agent_version_id: str            # which Da Vinci produced the original

CorrectionKind (StrEnum):
  TEXT_EDIT
  FONT_CHANGE
  COLOR_CHANGE
  TRANSFORM_MOVE
  TRANSFORM_SCALE
  TRANSFORM_ROTATE
  REGEN_WITH_NEW_PROMPT
  REORDER
  DELETE
  REPLACE_PROP
  REPLACE_CHARACTER
  EFFECT_ADD
  EFFECT_REMOVE
  EFFECT_PARAMS_CHANGE
  BLEND_MODE_CHANGE
  OPACITY_CHANGE
  PAGE_REORDER
  LAYOUT_APPLY
  ALT_TEXT_EDIT
  UNDO

CorrectionSource (StrEnum):
  DIRECT_MANIP    # user drag/click/edit on canvas
  CHAT            # user typed correction in chat
  AUTO_FIX        # user accepted a preflight fix suggestion

CorrectionContext (frozen):
  doc_kind: DocumentKind
  age_band: AgeBand | None
  brand_kit_id: str | None
  style_lock_id: str | None
  page_kind: str                   # cover, interior, etc.
  surrounding_layer_kinds: tuple[str, ...]
  prior_corrections_in_session: int

LayerSnapshot (frozen):
  layer_id: str
  source: LayerSource              # full source data
  effects: tuple[Effect, ...]
  transform: LayerTransform
  blend_mode: BlendMode
  opacity: float
  visible: bool
```

`LayerSnapshot` is intentionally a full snapshot, not a diff — corrections
are infrequent (10% of layers) and full snapshots make analysis trivial.

## Capture pipeline

```
def capture_correction(
    user_id, document_id, page_id, layer_id,
    kind, before_snapshot, after_snapshot,
    source: CorrectionSource,
    context: CorrectionContext,
) -> Correction:
    # 1. Compute inferred_intent via vision/diff-LLM
    intent = infer_intent(kind, before_snapshot, after_snapshot, context)
    # 2. Compute initial signal_strength (refined at aggregation)
    strength = initial_strength(kind, before_snapshot, after_snapshot)
    # 3. Persist
    correction = Correction(...)
    correction_store.save(correction)
    # 4. Side-effect: publish event for §20 aggregator
    event_bus.publish("correction.created", correction.id)
    return correction
```

## Hooks (where capture fires)

| Hook | When | Source |
|---|---|---|
| `layer_update` action handler | any UI/agent layer mutation by user | DIRECT_MANIP if user, ignored if agent |
| Chat tool: `apply_user_revision` | chat-driven correction | CHAT |
| `preflight_fix` action handler | user accepts fix suggestion | AUTO_FIX |
| `version_revert` (within 60s) | flag predecessor `reverted=True` | UNDO |

## Intent inference

Diff-LLM call (cheap; small model):

```
prompt = f"""
A user has tweaked an AI-generated illustration layer.
Layer kind: {kind}
Before: {before_snapshot_summary}
After:  {after_snapshot_summary}
Context: doc kind {doc_kind}, age band {age_band}, brand_kit {brand_kit_id}.

In one sentence, infer the user's intent. Be specific and observable; do not editorialise.
"""
```

Examples:
- "User changed Comic Sans → Atkinson Hyperlegible — likely accessibility preference."
- "User shifted character left by ~80px — likely composition rebalance for safe area."
- "User regenerated background with 'darker, more dramatic' — likely mood adjustment."

Cached by `(before_hash, after_hash)`; same edit = same intent inference.

## Signal strength initial

Heuristic, refined at aggregation time:

| Heuristic | Multiplier |
|---|---|
| Same kind already corrected ≥ 3 times by user across docs | × 2.0 |
| Within first 30 seconds of layer creation | × 0.6 (probably immediate refinement, weaker) |
| Late session (after many other corrections) | × 0.8 |
| Reverts an agent's regen with a new prompt | × 1.5 |
| Aligns with brand kit value (e.g. swapped to brand colour) | × 1.5 |
| Conflicts with a previously-promoted learning | × 0.5 (resolution needed) |

Bounded to [0.1, 2.0]; clipped at storage.

## Storage

```sql
CREATE TABLE corrections (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  user_id UUID NOT NULL,
  document_id UUID NOT NULL,
  page_id UUID NOT NULL,
  layer_id UUID,
  session_id UUID NOT NULL,
  kind TEXT NOT NULL,
  before JSONB NOT NULL,
  after JSONB NOT NULL,
  source TEXT NOT NULL,
  inferred_intent TEXT NOT NULL DEFAULT '',
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  signal_strength REAL NOT NULL DEFAULT 1.0,
  reverted BOOLEAN NOT NULL DEFAULT FALSE,
  reverted_at TIMESTAMPTZ,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  agent_version_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX corrections_user_kind_ts_idx ON corrections (tenant_id, user_id, kind, timestamp DESC);
CREATE INDEX corrections_document_idx ON corrections (document_id, timestamp DESC);
```

## Retention

- Corrections retained 365 days (longer than versions: training matters)
- Per memory rules (CLAUDE.md): contradictions resolved at aggregation;
  stale corrections decay weight but data preserved
- User can opt out per Document or globally
- Cross-tenant aggregation is forbidden

## API surface

| Action | Args | Returns |
|---|---|---|
| `correction_capture` | (called by handlers, not user-facing) | Correction |
| `correction_list` | `[document_id, user_id, kind, since, limit]` | tuple[Correction, ...] |
| `correction_get` | `correction_id` | Correction |
| `correction_revert_link` | `correction_id, version_id` | Correction with reverted=True |
| `correction_export` | `user_id, [filters]` | bytes (jsonl, for user data export) |
| `correction_delete` | `user_id, [filters]` | count deleted (right-to-erase) |

## Edge cases

1. **Agent makes a correction (not user)** — not captured; only user-source
   corrections feed learning.
2. **Identical correction repeated rapidly** (e.g. user toggling a checkbox)
   — coalesce within 5s window.
3. **Correction immediately followed by undo** — mark `reverted=true`;
   excluded from aggregation but preserved for analysis.
4. **Massive bulk action** (apply brand kit across whole book changes 200
   colours) — emit as a single aggregate correction, not 200.
5. **Correction during wizard** — captured but tagged `source=WIZARD`;
   excluded from regular aggregation (wizard intent is exploratory).
6. **Correction without an `agent_version_id`** (legacy) — accepted; no
   regression-tracking.
7. **PII in `before`/`after` snapshots** (user-typed text content) — stays
   tenant-scoped; included in user-data deletion sweeps.
8. **High-volume user** (1000s of corrections/day) — rate-limit capture per
   second to prevent runaway storage; user warned.
9. **Snapshot too large** (raster bytes inline) — store blob refs only, not
   pixels; differential summary in metadata.

## Errors

- `CorrectionStorageError(StrongholdError)` — DB write failed (rare)
- `IntentInferenceUnavailableError(RoutingError)` — diff-LLM down;
  correction stored without intent; back-fill job

## Test surface

- Unit: capture pipeline produces valid Correction; signal_strength bounded;
  every CorrectionKind serializable.
- Integration: a sequence of UI actions produces expected Correction stream;
  revert within 60s flags prior; coalescing within 5s works.
- Security: cross-tenant correction_list returns nothing; user-data export
  contains all and only user's own corrections; delete sweep is complete.
- Property: replaying corrections reconstructs end state from start.

## Dependencies

- existing `LearningStore` protocol pattern (target consumer)
- diff/vision-LLM (cheap, existing)
- §02 document, §23 versioning (revert detection)
