# 10 — Book & Page Layouts

**Status**: P0 / Document phase. Bridges Page model with template authoring.
**One-liner**: named layouts assign content into known slots on a Page;
applied via `layout_apply`, mutated freely afterward.

## Problem it solves

A picture book has predictable page structures: full-bleed art, art-with-
caption, double-spread, title page, copyright page. Without layouts, the
agent re-derives the structure each page; with layouts, it picks the right
shape and fills slots.

## Layouts catalogue

```
LayoutKind (StrEnum):
  FULL_BLEED            # 1 art layer covering bleed; no text
  ART_WITH_CAPTION      # art (top 2/3) + text (bottom 1/3)
  ART_WITH_BODY         # art + multi-paragraph body
  DOUBLE_SPREAD         # art across two facing pages (verso + recto)
  TEXT_ONLY             # body + drop-cap; chapter starts
  VIGNETTE              # spot illustration + body wraps
  COVER                 # title + byline + hero art + spine + back
  TITLE_PAGE            # large title + subtitle + author
  COPYRIGHT_PAGE        # © metadata, ISBN, edition
  DEDICATION_PAGE       # short centred dedication
  FRONT_MATTER          # contents, foreword, etc.
  BACK_MATTER           # author bio, acknowledgements
  POSTER                # single-page, large-format hero composition
  INFOGRAPHIC_GRID      # N-column grid with charts/icons/text
  INFOGRAPHIC_FLOW      # vertical scrolling flow with sections
```

## Data model

```
Layout (frozen):
  kind: LayoutKind
  slots: tuple[LayoutSlot, ...]
  options: Mapping[str, Any]      # layout-specific tweaks (margins, ratios)

LayoutSlot (frozen):
  id: str                          # "art", "caption", "title", "byline"
  layer_type: LayerType            # raster | text | shape | group
  bbox: BBox                       # (x, y, w, h) in page coords
  required: bool = True
  description: str = ""            # shown in editor
  default_style_overrides: Mapping[str, Any]  # font, weight, alignment
  generative_prompt_template: str = ""        # for "regenerate this slot"
```

`Layout` is data — not a database table by itself. Layouts are built-in
catalogue entries plus user-authored templates (§17). Applying a layout to a
Page does not store the Layout; it records `Page.layout_kind` and stamps slot
ids onto the layers it created/positioned.

```
Page.layout_kind: LayoutKind | None         # added field
Page.layout_options: Mapping[str, Any]
Layer.slot_id: str | None                    # which slot this layer fills
```

## Layout application

```
def layout_apply(page, layout):
    # 1. snapshot current layers (for undo)
    # 2. detect existing layers with matching slot_ids → keep, retransform
    # 3. for missing required slots: emit a placeholder layer (empty text /
    #    placeholder gradient art / placeholder shape)
    # 4. for extra layers (not in layout slots): keep them as "free" layers,
    #    mark with metadata; agent rule: warn user
    # 5. set Page.layout_kind, Page.layout_options
```

Applying a layout is non-destructive: existing content stays, just gets
re-positioned to match slots when slot_ids align.

## Layout per DocumentKind defaults

| DocumentKind | Default page layouts (page index → layout) |
|---|---|
| `picture_book` | 0=COVER, 1=TITLE_PAGE, 2=COPYRIGHT_PAGE, 3=DEDICATION_PAGE, 4..N-2=ART_WITH_CAPTION, N-1=BACK_MATTER |
| `early_reader` | 0=COVER, 1=TITLE_PAGE, 2=COPYRIGHT_PAGE, 3..N=ART_WITH_BODY |
| `poster` | single page = POSTER |
| `infographic` | single page = INFOGRAPHIC_FLOW or _GRID per user choice |

The wizard (§32) uses these to skeleton a Document.

## Verso/recto awareness

Picture books bind on the spine. Master pages can specify mirrored margins:

```
PageMargin (frozen):
  binding_edge: int     # gutter side; depends on verso/recto
  outer_edge: int
  top: int
  bottom: int
```

Page ordering parity (even=verso, odd=recto) drives which side is the binding
edge. Layouts respect this when computing slot bboxes.

## Pagination helpers (for early readers)

```
def pages_for_word_count(text, age_band, layout=ART_WITH_BODY) -> int:
    words_per_page = AGE_BAND_WPP[age_band]   # e.g. 60 for ages 5-7
    return max(1, ceil(len(text.split()) / words_per_page))

def auto_paginate(manuscript, age_band) -> tuple[Page, ...]:
    # Splits text on natural breaks (paragraph, sentence, line)
    # Inserts spot illustration markers at scene breaks
```

## Page furniture (auto-fill from doc metadata)

| Slot | Source |
|---|---|
| `title` | `Document.metadata["title"]` |
| `subtitle` | `Document.metadata["subtitle"]` |
| `byline` | `Document.metadata["author"]` |
| `copyright` | `© {year} {author}. All rights reserved.` |
| `isbn` | `Document.metadata["isbn"]` (if present) |
| `dedication` | `Document.metadata["dedication"]` |
| `page_number` | `Page.ordering` (with verso/recto alignment) |

## API surface

| Action | Args | Effect |
|---|---|---|
| `layout_apply` | `page_id, kind, [options]` | (re)positions layers into slots |
| `layout_list_kinds` | `[doc_kind]` | available layouts (filtered) |
| `layout_describe` | `kind` | slot list + bboxes + defaults |
| `auto_paginate` | `manuscript_text, age_band, layout` | tuple of new Page objects |
| `page_furniture_apply` | `page_id` | fills slots from doc metadata |

## Edge cases

1. **Apply layout that conflicts with existing layers** — non-slot layers
   preserved as "free"; warning issued.
2. **Apply COVER layout to non-first page** — allowed (e.g. back cover); UI
   warns.
3. **Picture book document with odd page count** — pre-flight WARNs.
4. **Auto-paginate text with mid-paragraph scene break markers** — split on
   markers; require minimum 30 words per page after split (else merge).
5. **Master page conflicts with applied layout** — master wins for fixed
   elements (page number, frame); layout fills the remaining bbox.
6. **Layout with required slot has no content** — placeholder; pre-flight
   surfaces "incomplete page".
7. **Re-apply layout to a page already with the same kind** — no-op or
   re-snap to slot positions if drifted.
8. **Layout applied across orientation change** (portrait page → landscape
   page) — slot bboxes recomputed proportionally; warn on aspect mismatch.

## Errors

- `LayoutKindUnknownError(ConfigError)`
- `SlotMissingRequiredError(ConfigError)` — only on `layout_validate`,
  not on apply (apply is permissive)

## Test surface

- Unit: every LayoutKind has a slot list; bboxes are within page bounds;
  required slots reachable.
- Integration: apply COVER → 4 layers (title, subtitle, byline, art) at
  expected positions; auto-paginate 5000 words at age 5-7 → ~83 pages
  (60 wpp); page furniture fills metadata.
- Property: applying same layout twice is idempotent (modulo placeholder
  ids).

## Dependencies

- §02 document model, §05 text, §06 shapes, §11 templates
