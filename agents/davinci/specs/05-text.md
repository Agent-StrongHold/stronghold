# 05 — Text

**Status**: P0. Books and posters live on type.
**One-liner**: text is a first-class layer with full typographic control,
rendered by Pillow + fontTools (vector-aware), never baked into AI images.

## Problem it solves

Today the `text` action renders single-style text via Pillow. For books and
posters we need: drop caps, pull quotes, callouts, speech bubbles, text on
paths, multiple weights/widths, character/word/line spacing, text-to-shape
conversion, and tenant-uploaded fonts.

## Data model

```
TextSource (frozen):
  content: str
  style: TextStyle
  layout: TextLayout

TextStyle (frozen):
  font_family: str = "Inter"
  font_weight: FontWeight = REGULAR     # THIN..BLACK
  font_width: FontWidth = NORMAL        # CONDENSED..EXPANDED (variable fonts)
  font_slant: float = 0.0               # italic axis for variable fonts
  size_px: int = 48
  color: Color = "#000000"
  letter_spacing: float = 0.0           # em units
  word_spacing: float = 0.0
  line_height: float = 1.2
  underline: bool = False
  strikethrough: bool = False
  text_transform: TextTransform = NONE  # NONE | UPPERCASE | LOWERCASE | TITLECASE
  fill_image_id: str | None = None      # texture fill (poster cliché)

TextLayout (frozen):
  alignment: Alignment = LEFT           # LEFT | CENTER | RIGHT | JUSTIFY
  vertical_alignment: VAlignment = TOP  # TOP | MIDDLE | BOTTOM
  max_width_px: int | None = None       # auto-wrap; None = single line
  max_lines: int | None = None          # truncate with ellipsis if exceeded
  hyphenate: bool = False
  on_path_id: str | None = None         # render along a vector path layer
```

```
TextRun (frozen):                       # for inline style changes within content
  content: str
  style_overrides: Mapping[str, Any]    # only diff from parent TextStyle
```

`TextSource.content` may be a plain str OR a tuple of `TextRun` for rich
formatting (P1; P0 ships flat str).

## Special text features

| Feature | Implementation |
|---|---|
| Drop cap | First N lines wrap around an enlarged first letter; computed via Pillow `textbbox` |
| Pull quote | Style preset; centred, larger, with em-dash attribution |
| Callout / speech bubble | Composite of a shape layer (§06) + child text layer with internal padding |
| Text on path | Render glyphs along a Bézier path from a sibling shape layer |
| Curved banner | Shorthand for text-on-path with an arc geometry |
| Text fill from image | `fill_image_id` masks the image to the glyph silhouette |
| Text to shape | `text_to_shape` action converts glyphs to `ShapeSource` paths |
| Variable fonts | `font_weight`, `font_width`, `font_slant` map to OT variation axes |

## Font registry

| Source | Storage |
|---|---|
| Bundled | `agents/davinci/fonts/` — Inter, Roboto, Playfair, JetBrains Mono, Lora, Atkinson Hyperlegible (kid-friendly) |
| Tenant uploaded | `font_blobs` table, scoped by tenant_id, validated for safe TTF/OTF tables only |
| Variable | bundled + tenant; variations exposed as axes |

Font fallback chain: requested family → bundled fallbacks per script (Latin,
Latin Extended, Cyrillic, Greek, Arabic, CJK) → "Last Resort" font that boxes
unknown glyphs with their codepoint.

## API surface (canvas tool actions)

| Action | Args | Effect |
|---|---|---|
| `text` (existing, extended) | `content, style, layout, position, [page_id]` | new text layer |
| `text_update` | `layer_id, content?, style?, layout?` | replace fields |
| `text_to_shape` | `layer_id` | converts to ShapeSource path layer |
| `font_upload` | `tenant_id, file_bytes` | validate + store |
| `font_list` | `[tenant_only]` | bundled + tenant fonts |
| `drop_cap` | `layer_id, lines: int` | wrap-aware drop cap effect |

## Edge cases

1. **Text overflows max_width** — wrap on whitespace; if a single word exceeds
   width, hyphenate (if enabled) else break mid-word.
2. **Text overflows max_lines** — truncate; append ellipsis (`…`) within the
   last line's measured width.
3. **Missing glyph** — fall through script-aware fallbacks; final fallback
   draws a `□` box; agent gets a `MissingGlyphWarning` in result.
4. **Variable font axis out of range** — clamp to font's defined range; warn.
5. **Custom font with malicious tables** — reject at upload (validate against
   safe-table whitelist: cmap, glyf, head, hhea, hmtx, loca, maxp, name, post,
   OS/2, fvar, gvar, GSUB, GPOS, cvt, fpgm, prep). All others stripped.
6. **Text on a closed path** — start point is path's first vertex; wraps
   continuously.
7. **Text on a path shorter than the rendered string** — overflow truncated
   with ellipsis; warn.
8. **RTL text** (Arabic, Hebrew) — full bidi via `python-bidi`; ligature
   shaping via `uharfbuzz`.
9. **Emoji** — colour glyphs via Apple/Twemoji bundled fallback; reject
   private-use codepoints unless tenant has uploaded matching font.
10. **`text_to_shape` on an animated text** — disallowed (animation is video,
    handled separately in §15).

## Errors

- `FontNotFoundError(SkillError)`
- `FontValidationError(SecurityError)` — unsafe tables in upload
- `MissingGlyphWarning` (warning, not error; surfaced in result metadata)
- `TextOverflowWarning` (same)
- `TextOnPathLengthError(ConfigError)`

## Test surface

- Unit: every TextStyle/TextLayout default; clamps; transform application;
  drop-cap math; truncation math.
- Integration: rendering a TextLayout matches a stored fixture PNG (golden
  tests, with tolerance for sub-pixel anti-alias differences).
- Security: malicious TTF (with TT instructions / `prep` table > 1KB)
  rejected; bandit clean; no `eval`/`exec` in font path.
- Property (hypothesis): for any TextStyle, render is deterministic given
  same content + style + font version.

## Dependencies

- Pillow (existing)
- `fontTools` (new) — variable font axis manipulation, table validation
- `uharfbuzz` (new) — shaping
- `python-bidi` (new) — RTL bidi algorithm
- Bundled font set (LICENSE-compatible: SIL OFL or Apache-2.0)
