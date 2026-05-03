# 08 — Print Specification

**Status**: P0 / Trust phase. Required before any export to physical media.
**One-liner**: every Page declares trim/bleed/safe-area/DPI/color-mode; every
generative call respects target DPI; export embeds the right ICC profile.

## Problem it solves

A children's book or poster that looks fine on screen fails at the printer
when text crosses bleed, fonts aren't embedded, raster sources are below
300 DPI, or colour appears wildly different from preview. The print spec
turns "looks ok" into "press-ready" by encoding the rules at the data layer.

## Data model

```
PrintSpec (frozen):
  trim_size: tuple[int, int]       # final cut dimensions in pixels at dpi
  dpi: int = 300                    # 72/150/300/600 standard
  bleed: int = 38                   # px = 0.125" @ 300 DPI; 3mm metric
  safe_area: int = 75               # px = 0.25" @ 300 DPI
  color_mode: ColorMode = SRGB
  icc_profile: str | None = None    # e.g. "ISO_Coated_v2_300_eci"
  binding: BindingKind = NONE       # NONE | PERFECT | SADDLE_STITCH | SPIRAL | HARDCOVER

ColorMode (StrEnum):
  SRGB        # screen / digital
  CMYK        # press
  GRAYSCALE   # economy print

BindingKind (StrEnum):
  NONE
  SADDLE_STITCH    # staples through fold; <= 64 pages
  PERFECT          # glued spine; 32-800 pages
  SPIRAL           # wire-o
  HARDCOVER        # case-bound
```

## Standard page sizes

| Name | Trim (in) | Pixels @300 DPI | Use |
|---|---|---|---|
| US Letter | 8.5×11 | 2550×3300 | docs, posters small |
| A4 | 8.27×11.69 | 2480×3508 | int'l docs/posters |
| A3 | 11.69×16.53 | 3508×4961 | larger posters |
| A2 | 16.53×23.39 | 4961×7016 | infographics, posters |
| A1 | 23.39×33.11 | 7016×9933 | gallery posters |
| Tabloid | 11×17 | 3300×5100 | broadsheet posters |
| Picture book square | 8×8 | 2400×2400 | classic kids book |
| Picture book portrait | 8.5×11 | 2550×3300 | standard kids book |
| Board book | 6×6 | 1800×1800 | toddler |
| Movie poster | 24×36 | 7200×10800 | one-sheet |
| Photo 4×6 | 4×6 | 1200×1800 | print |
| Custom | user | user | reach goal: validate |

Defaults table lives in code; `print_spec_named("picture_book_8x8", dpi=300)`
helper.

## Bleed math (worked example)

For a `picture_book_8x8` at 300 DPI with default 0.125" bleed and 0.25" safe:
- Trim canvas: 2400 × 2400 px (visible)
- Bleed canvas: 2476 × 2476 px (extends 38 px each side; everything must paint
  to this edge to avoid white slivers post-cut)
- Safe area: 2250 × 2250 px (centred; critical text MUST stay inside)

Page rendering produces the bleed canvas; export crops to bleed for the press,
or to trim for the digital preview.

## Generative DPI enforcement

When a generative action targets a layer destined for a print Page:

1. Compute layer's *target physical size* in inches: `layer_width_px / dpi`
2. Compute its *required pixel size at print DPI*:
   `target_inches × print_spec.dpi`
3. If generation request would yield fewer pixels: either upscale post-gen
   (§04 upscale) or reject with `DPILowError(ConfigError)` if upscale would
   exceed quality threshold.
4. Cache the print-DPI rendition; agent uses draft tier for iteration but
   final composite uses the high-DPI render.

## Pre-flight contributions

Print spec defines several pre-flight checks (full check list in §22):

| Rule | Check |
|---|---|
| `text_in_safe_area` | All text layer bboxes must lie inside `safe_area` rect |
| `bg_covers_bleed` | At least one background layer covers the full bleed canvas |
| `dpi_minimum` | Every raster layer ≥ `print_spec.dpi` at its rendered scale |
| `colors_in_gamut` | If `color_mode=CMYK`, all colours convert without out-of-gamut warnings (or operator opted in) |
| `fonts_embeddable` | Every used font has Embedding Permission ≥ Editable |
| `binding_safe` | If saddle-stitch and ≥ 64 pages, warn (creep too high) |
| `page_count_parity` | Picture books should be multiples of 4 (signature) — warn if not |

## CMYK conversion

Conversion happens at export time, not in the canvas. Reasons:
- Editing in CMYK is slower and limits effects (most Pillow ops are RGB-native)
- Vision models output sRGB; converting per gen wastes time
- Accurate conversion needs ICC profiles which depend on the printer

Pipeline:
- Convert each rendered layer from sRGB → CMYK using `littlecms` (`Pillow`
  ImageCms with target profile)
- Embed the target ICC profile into the PDF
- For pure black text, set rich-black recipe `(C0 M0 Y0 K100)` rather than
  the converted CMYK to avoid registration issues

## Edge cases

1. **Mixed DPI raster layers** — each layer carries its native DPI; the
   composite uses the page DPI; warn if any layer is below.
2. **Bleed missing on a background layer** — pre-flight fails; the agent
   suggests outpaint (§04) of the background by `bleed` px.
3. **CMYK mode with sRGB colours that fall outside CMYK gamut** — warn per
   colour with the closest in-gamut substitute; require operator confirm to
   proceed.
4. **Custom trim with non-finite numbers** — reject at construction.
5. **Variable trim per page in same document** — allowed (cover may differ
   from interior); export bundles them as a multi-trim PDF or separate files.
6. **Hardcover binding** — case wrap math (spine width = page count × paper
   thickness + cover board); separate spec for cover; not in P0, P1 reach.
7. **Foil stamp / spot UV** — out of scope; export as separate spot-color PDF
   (P3).

## Errors

- `DPILowError(ConfigError, code="DPI_LOW")`
- `OutOfGamutWarning` (warning, not error)
- `BleedMissingError(ConfigError, code="BLEED_MISSING")`
- `FontNotEmbeddableError(SecurityError, code="FONT_NOT_EMBEDDABLE")`
- `InvalidPageSizeError(ConfigError, code="INVALID_PAGE_SIZE")`

## Test surface

- Unit: every standard size constructs at correct pixel dims for each DPI;
  bleed/safe-area math; ICC profile name validation.
- Integration: full Page render at 300 DPI; CMYK conversion round-trip; PDF
  export embeds correct ICC; pre-flight catches text-in-bleed.
- Property (hypothesis): for any `(trim_inches, dpi)`, computed pixel dims
  satisfy `pixels == round(inches × dpi)` exactly.
- Performance (`@perf`): A2 print render < 8 s on dev hardware.

## Dependencies

- `Pillow` `ImageCms` (built-in for ICC)
- ICC profiles: bundled `ISOcoated_v2_eci.icc`, `sRGB_v4_ICC_preference.icc`
- `littlecms` (transitive via Pillow)
