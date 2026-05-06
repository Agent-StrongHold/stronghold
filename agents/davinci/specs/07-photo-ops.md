# 07 — Photo Ops (Adjustments, Filters, Blend Modes)

**Status**: P2 minimum (subset). Full set at P3.
**One-liner**: standard raster image-editing operations as `Effect` entries
on a Layer's effect stack (§01).

## Problem it solves

For book covers and posters, occasional brightness/contrast/saturation tweaks,
shadow drops, and overlay blending are needed. We don't need full Photoshop.
Decide once what's in the P2 minimum and ship it; defer curves/levels/etc.

## P2 minimum (ships in phase 5)

| EffectKind | Params | Backend |
|---|---|---|
| `BRIGHTNESS` | `value: float [-1, 1]` | Pillow `ImageEnhance.Brightness` |
| `CONTRAST` | `value: float [-1, 1]` | Pillow `ImageEnhance.Contrast` |
| `SATURATION` | `value: float [-1, 1]` | Pillow `ImageEnhance.Color` |
| `HUE_SHIFT` | `degrees: int [-180, 180]` | numpy HSV cycle |
| `EXPOSURE` | `stops: float [-3, 3]` | numpy linear scale |
| `GAMMA` | `value: float [0.1, 5.0]` | Pillow `ImageOps` |
| `INVERT` | none | Pillow `ImageOps.invert` |
| `GAUSSIAN_BLUR` | `radius_px: float [0, 100]` | Pillow `ImageFilter.GaussianBlur` |
| `SHARPEN` | `amount: float [0, 5]` | Pillow `ImageFilter.UnsharpMask` |
| `NOISE_ADD` | `amount: float [0, 1], monochrome: bool` | numpy |
| `VIGNETTE` | `strength: float [0, 1], roundness: float [0, 1]` | numpy radial mask |
| `DROP_SHADOW` | `dx, dy, blur, color, opacity` | composite of blurred mask |
| `INNER_SHADOW` | same | composite, masked to layer alpha |
| `OUTER_GLOW` | `blur, color, opacity, spread` | composite of blurred dilated mask |
| `STROKE` | `width, color, position` | composite of dilated/eroded outlines |

## Blend modes

Per-layer `blend_mode: BlendMode`, applied at composite time (not as effect).

| BlendMode | Formula (per channel, normalized 0..1) |
|---|---|
| NORMAL | `Cb` (back), `Cs` overlay only |
| MULTIPLY | `Cb * Cs` |
| SCREEN | `1 - (1-Cb)(1-Cs)` |
| OVERLAY | `Cb<0.5 ? 2 Cb Cs : 1 - 2(1-Cb)(1-Cs)` |
| SOFT_LIGHT | W3C SVG soft-light formula |
| HARD_LIGHT | inverse of overlay |
| DARKEN | `min(Cb, Cs)` |
| LIGHTEN | `max(Cb, Cs)` |
| DIFFERENCE | `\|Cb - Cs\|` |
| EXCLUSION | `Cb + Cs - 2 Cb Cs` |
| COLOR_DODGE | `Cb / (1 - Cs)` clipped |
| COLOR_BURN | `1 - (1-Cb)/Cs` clipped |
| HUE | HSL: H from src, S+L from back |
| SATURATION | HSL: S from src |
| COLOR | HSL: H+S from src |
| LUMINOSITY | HSL: L from src |

Implementation: ~80 lines of numpy per-mode. Frozen alpha-composite at the end
applies layer `opacity`.

## P3 deferred (not blocking books/posters/infographics)

`LEVELS`, `CURVES`, `COLOR_BALANCE`, `BLACK_AND_WHITE`, `POSTERIZE`,
`THRESHOLD`, `CHROMATIC_ABERRATION`, `BEVEL_EMBOSS`, `MOTION_BLUR`,
`RADIAL_BLUR`, `PIXELATE`, `MOSAIC`, `DENOISE`, `GRAIN`.

## Edge cases

1. **Effect on a 1×1 layer** — applied; trivial render. Used by some auto-fill
   patterns.
2. **Vignette on non-rectangular alpha** — vignette respects layer alpha;
   transparent regions stay transparent.
3. **Drop shadow with `dx == 0 && dy == 0 && blur == 0`** — visible only if
   `color` is opaque and matches background; warn.
4. **Stroke with `width == 0`** — no-op; warn.
5. **Hue shift on greyscale** — no visible change (saturation 0); allowed.
6. **Blend mode on a layer with full opacity AND opaque blend mode (e.g.
   normal)** — equivalent to no blend; cache hit on baseline.
7. **Effect chain with conflicting saturation calls** — each applied in
   sequence; agent decides desired final state.

## Errors

- Reuses `EffectParamsError` from §01.

## Test surface

- Unit: each kind validates params; out-of-range raises; clamp behaviour
  documented per kind.
- Golden: known-input known-output PNGs per kind at 100×100 fixture;
  tolerance for floating-point fuzz across CPU architectures (max 1/255 per
  channel diff).
- Property: `INVERT(INVERT(x)) == x`; `BRIGHTNESS(0)` is identity;
  `MULTIPLY(WHITE, x) == x`; `SCREEN(BLACK, x) == x`.
- Performance (`@perf`): full P2 effect on 4096×4096 layer < 200ms.

## Dependencies

- Pillow (existing)
- numpy (added in §01)
- No new deps for P2
