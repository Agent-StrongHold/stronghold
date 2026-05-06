# 01 — Effect Stack

**Status**: P0 / Foundation. Blocks 03, 04, 07, 14.
**One-liner**: every Layer carries an ordered list of non-destructive effects;
the rendered output is `source → effects → mask → blend → composite`.

## Problem it solves

Today `Layer.image_data: bytes` is a baked PNG. Any adjustment (brightness,
blur, color shift, drop shadow) would either:
- mutate the bytes (destructive — can't undo without storing every prior state)
- fork a new layer per adjustment (explodes layer count, breaks identity)

Neither is acceptable for the iterative book / poster workflow where the agent
applies, removes, and re-applies effects until a page reads right.

## Data model

```
Layer:
  id: str
  name: str
  layer_type: LayerType            # raster | shape | text | group
  source: LayerSource              # tagged union (see below)
  effects: tuple[Effect, ...]      # ordered, applied head→tail
  mask: Mask | None
  blend_mode: BlendMode = NORMAL
  opacity: float = 1.0             # 0.0 .. 1.0
  x: int
  y: int
  scale: float = 1.0
  rotation: float = 0.0            # degrees, -360..360
  z_index: int = 0
  visible: bool = True
  metadata: dict[str, Any]         # generation prompt, model, cost, etc.
```

### LayerSource (tagged union)

```
RasterSource:    {kind: "raster", image_bytes: bytes, width: int, height: int}
ShapeSource:     {kind: "shape", geometry: ShapeGeometry, fill, stroke}
TextSource:      {kind: "text", content: str, style: TextStyle}
GroupSource:     {kind: "group", child_layer_ids: tuple[str, ...]}
```

### Effect

```
Effect:
  id: str                      # so it can be referenced for remove/disable
  kind: EffectKind             # see EffectKind enum
  params: Mapping[str, Any]    # validated against kind's schema
  enabled: bool = True
```

### EffectKind (enum, P0 subset)

Adjustments: `BRIGHTNESS`, `CONTRAST`, `SATURATION`, `HUE_SHIFT`,
`TEMPERATURE`, `EXPOSURE`, `GAMMA`, `INVERT`.

Filters: `GAUSSIAN_BLUR`, `MOTION_BLUR`, `SHARPEN`, `UNSHARP_MASK`, `NOISE_ADD`,
`VIGNETTE`, `PIXELATE`.

Layer styles: `DROP_SHADOW`, `INNER_SHADOW`, `OUTER_GLOW`, `INNER_GLOW`,
`STROKE`, `GRADIENT_OVERLAY`, `COLOR_OVERLAY`.

P1 (deferred to phase 5): `LEVELS`, `CURVES`, `COLOR_BALANCE`, `BLACK_AND_WHITE`,
`POSTERIZE`, `THRESHOLD`, `CHROMATIC_ABERRATION`, `BEVEL_EMBOSS`.

## Render pipeline

```
def render(layer) -> Image:
    img = rasterize(layer.source)             # vector → bitmap if needed
    for fx in layer.effects:
        if fx.enabled:
            img = apply_effect(fx, img)
    if layer.mask:
        img = apply_mask(img, layer.mask)
    return img  # composited later with blend_mode + opacity
```

### Caching

Each layer caches `(source_hash, effects_hash, mask_hash) → rendered_bytes`.
- `effects_hash` = `hash(tuple((fx.kind, fx.params, fx.enabled) for fx in effects))`
- Cache is per-process LRU with 64 MB cap; spills to disk per-Document for
  warm-restart.
- Cache is invalidated on any Layer mutation; immutable Layer objects make this
  cheap (replace, don't mutate).

## API surface (canvas tool actions)

| Action | Args | Effect |
|---|---|---|
| `effect_add` | `layer_id, kind, params, [position]` | Append (or insert at index) |
| `effect_update` | `layer_id, effect_id, params` | Replace params |
| `effect_remove` | `layer_id, effect_id` | Drop from stack |
| `effect_toggle` | `layer_id, effect_id, enabled` | Flip without removing |
| `effect_reorder` | `layer_id, ordering: tuple[str, ...]` | New order of ids |
| `layer_blend` | `layer_id, blend_mode, opacity` | Set composite props |

## Edge cases

1. **Effect on a group layer** — applies to the group's *composited* output,
   not each child individually. Document this clearly; it's a common confusion.
2. **Effect on a text layer pre-rasterization** — text vectors get rasterized
   first; downstream blur/shadow operates on pixels. Effects that need vector
   data (e.g. text-on-path warp) must be modelled as text-layer properties, not
   stack effects.
3. **Effect with invalid params** — schema-validated at insertion; `ConfigError`
   subclass `EffectParamsError` raised; layer state unchanged.
4. **Effect order matters** — `BLUR` before `STROKE` softens the stroke;
   `STROKE` before `BLUR` blurs the stroke. We don't reorder for the agent;
   document the ordering in agent rules.
5. **Empty effect stack** — render returns rasterized source unchanged.
6. **Effect on an empty raster** (0×0) — no-op, return unchanged.
7. **Disabled effect in middle of stack** — skipped; doesn't break stack hash.
8. **Maximum stack depth** — soft cap at 32 effects per layer; warn at 16.
9. **Cycle in group → group reference** — Layer source of kind `group` cannot
   transitively reference itself; validated at insertion.

## Errors

- `EffectKindUnknownError(SkillError)` — unknown EffectKind enum value
- `EffectParamsError(ConfigError)` — params fail schema validation
- `EffectStackOverflowError(ConfigError)` — > 32 effects on one layer

## Test surface

- Unit: each EffectKind validated for params schema, idempotence on no-op,
  disabled = passthrough, deterministic given same input + params + seed.
- Integration: stack of 5 effects produces same bytes regardless of cache
  state; toggle middle effect produces same bytes as removing it then
  re-adding at same position.
- Property (hypothesis): for any sequence of effect_add / effect_remove /
  effect_toggle that ends in the same logical state, render output is
  byte-identical.
- Performance (`@perf`): 16-effect stack on 4096×4096 layer renders in
  < 2 s on developer hardware.

## Dependencies

- Pillow ≥ 11 (current dep)
- numpy (pyproject add) — for blend modes, custom filters
- No new heavy deps for P0
