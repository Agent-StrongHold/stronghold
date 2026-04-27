# 09 — Style Lock

**Status**: P0 / Document phase. Core consistency mechanism.
**One-liner**: a per-Document constraint object that injects style direction
into every generative call and validates outputs against the locked style.

## Problem it solves

The single biggest "tell" of bad AI books is style drift across pages —
characters look different, palette shifts, line weight jumps. Character refs
solve identity. Style lock solves *everything else*: rendering style,
palette, line weight, lighting, mood.

## Data model

```
StyleLock (frozen):
  id: str
  tenant_id: str
  owner_id: str
  document_id: str | None          # may be reused across documents
  name: str                        # "warrior-knight v3"
  rendering_style_prompt: str      # natural-language style direction
  palette: tuple[Color, ...]       # 3-7 swatches; ordered by importance
  line_weight: LineWeight          # FINE | MEDIUM | BOLD | MIXED
  lighting: LightingDirection      # NATURAL | DRAMATIC | FLAT | RIM | NONE
  mood: MoodTag                    # PLAYFUL | EPIC | QUIET | etc.
  reference_image_blob_id: str | None    # the hero illustration
  reference_palette_extracted: bool      # did we extract the palette from ref?
  lora_id: str | None              # cross-ref §21; null until trained
  drift_threshold: float = 0.25    # 0..1; failed checks trigger warning
  created_at, updated_at
  version: int                     # monotonic; bumped on every refinement
```

```
StyleDriftScore (frozen):
  layer_id: str
  page_id: str
  lock_id: str
  lock_version: int
  score: float                     # 0..1; 0 = perfect, 1 = totally off
  components: Mapping[str, float]  # palette/style/line/lighting per-axis
  computed_at: datetime
  vision_llm_reasoning: str        # why the score is what it is
```

## Authoring flow

Style locks are created in three ways:

1. **From wizard (§32)** — user picks one of three mood-board thumbnails
   produced by Da Vinci; the chosen thumbnail becomes the seed; vision-LLM
   extracts palette + style description.
2. **From hero illustration** — once a "good" first page exists, "lock this
   style" extracts everything from that image.
3. **Manual brief** — user types the prompt + picks palette + chooses
   line-weight/lighting/mood.

The lock's `rendering_style_prompt` is auto-injected into every subsequent
generation as a suffix:

```
Final prompt = "{user_prompt}, in {style.rendering_style_prompt} style,
                using palette of {style.palette[:3]},
                with {style.line_weight} line work,
                {style.lighting} lighting"
```

Order matters: user prompt first (subject/composition), style suffix last
(direction).

## Drift checking

After each generation in a document with a style lock, a vision-LLM compares
the generated image against the lock's reference + textual description:

```
def drift_score(layer, lock) -> StyleDriftScore:
    response = vision_llm.compare(
        new_image=layer.rendered_bytes,
        reference_image=lock.reference_image_bytes,
        reference_description=lock.rendering_style_prompt,
        criteria=["palette", "rendering_style", "line_weight", "lighting"],
    )
    return StyleDriftScore(
        score=response.overall,           # weighted mean of components
        components=response.per_axis,
        ...
    )
```

If `score > lock.drift_threshold`, the layer is flagged. Pre-flight (§22)
surfaces these. The agent's rule: do NOT auto-replace; report and ask.

## Refinement (manual)

The user can refine the lock:
- "add this colour to the palette"
- "make the lighting more dramatic"
- "tighten the threshold"

Refinement bumps `lock.version`. Pages generated under an older version
remain visually consistent (their drift was OK against the version they were
made under) but a per-page `lock_version` is recorded for traceability.

## Refinement (from corrections, cross-ref §20)

Once the corrections pipeline is active, aggregated user corrections drift
the lock toward observed taste:

| Correction kind | Lock effect |
|---|---|
| `COLOR_CHANGE` repeated 3+ times → same hue | append to palette; warn if conflicts |
| `FONT_CHANGE` repeated 3+ times → same family | propose brand-kit font swap (separate from lock) |
| `REGEN_WITH_NEW_PROMPT` repeated with same suffix terms | append terms to `rendering_style_prompt` |
| user removes a palette colour from generations | mark colour as "soft" (used for accents only) |

## API surface

| Action | Args | Returns |
|---|---|---|
| `style_lock_create_from_brief` | `name, prompt, palette, line_weight, lighting, mood` | StyleLock |
| `style_lock_create_from_image` | `image_blob_id, name, [overrides]` | StyleLock (extracts) |
| `style_lock_apply` | `document_id, lock_id` | document with lock_id |
| `style_lock_check` | `layer_id` | StyleDriftScore |
| `style_lock_check_page` | `page_id` | tuple[StyleDriftScore, ...] |
| `style_lock_refine` | `lock_id, fields` | new StyleLock with version+1 |
| `style_lock_save` | `lock_id` | persisted; tenant-scoped |
| `style_lock_load` | `name` | StyleLock |

## Edge cases

1. **Lock applied retroactively to existing pages** — drift-check old layers;
   surface findings to user; do NOT auto-regen.
2. **Generation with no lock** — fine; agent rule: warn the user that
   consistency may suffer.
3. **Lock palette includes only neutrals** — generations can use any colour
   for accent (palette is "preferred", not "exclusive"); users can tighten
   to "exclusive" mode (P1).
4. **Vision-LLM unavailable** — drift check returns `score=null,
   components={}`; pre-flight downgrades to INFO.
5. **Lock has no reference image** — drift uses textual description only;
   tracked accuracy lower.
6. **User edits style lock to unrealistic combination** — e.g., "watercolour"
   + "sharp vector lines" — agent warns at apply time, allows it.
7. **Cross-document lock reuse** — supported; document references the lock
   id, not a copy. Edits to the lock affect all referencing documents (with
   warning at apply time).
8. **LoRA trained from this lock** — once `lora_id` set, generation prefers
   LoRA over textual injection (cleaner signal).
9. **Style lock + brand kit conflict** — palette in lock vs palette in brand
   kit may differ; brand kit wins for UI/text colours, lock wins for
   illustration colours; conflicts surfaced.
10. **Reference image deleted** — lock keeps blob reference until
    explicitly removed; blob retention coordinates with §02.

## Errors

- `StyleLockNotFoundError(StrongholdError)`
- `StyleLockApplyConflictError(ConfigError)` — apply to doc that already has
  a different lock without `replace=true`
- `StyleDriftCheckUnavailableError(RoutingError)` — vision-LLM unreachable
  (downgraded by callers)

## Test surface

- Unit: lock invariants; palette ordering; version monotonicity; refinement
  bumps version.
- Integration: extract-from-image populates palette + description; apply
  injects suffix into prompts; drift-check on identical image returns ~0;
  drift-check on unrelated image returns > threshold.
- Property: `palette` in [3..7]; `drift_threshold` in [0..1].

## Dependencies

- vision-LLM (existing)
- palette extraction: `extcolors` or k-means in numpy
- §32 wizard, §22 preflight, §20 learning aggregation, §21 LoRA
