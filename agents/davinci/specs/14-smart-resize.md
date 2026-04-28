# 14 — Smart Resize

**Status**: P1 / Output phase. Posters and social media multiplier.
**One-liner**: re-layout a Page into a different aspect ratio while
preserving subject framing, text hierarchy, and brand consistency.

## Problem it solves

A movie poster at 24×36 needs versions for: 27×40, 11×17, 8.5×11, social
square (1:1), Instagram story (9:16), Twitter header (3:1). Doing this
manually is tedious; doing it badly stretches text, crops faces, or breaks
brand layout.

## Resize strategies

```
ResizeStrategy (StrEnum):
  STRETCH                # naive scale (rejected for non-trivial diff)
  CROP_TO_SUBJECT        # detect subject, frame around it
  REFLOW                 # re-position layers per slot rules
  REGENERATE_BACKGROUND  # outpaint or regen bg, keep subjects
  SMART_AUTO             # combine strategies based on layer kinds
```

`SMART_AUTO` is the default. Other strategies usable for power-user override.

## Algorithm (SMART_AUTO)

```
def smart_resize(page, target_size_px, strategy=SMART_AUTO):
    # 1. Classify layers: subject | background | text | decoration | logo
    # 2. Compute target bbox per role from layout slot rules
    # 3. For each layer:
    #    - background: regenerate or outpaint to cover target
    #    - subject: scale + reposition into subject bbox; preserve face/centroid
    #    - text: re-flow inside text bbox; auto-resize font if needed (within bounds)
    #    - decoration: scale to nearest fitting bbox
    #    - logo: pin to corner (preserves brand position)
    # 4. Produce a new Page with same layer ids but new transforms (versioning §23 captures the diff)
```

## Subject detection

Reuse §03 `auto_subject` mask + face detection (`mediapipe` or
existing rembg pipeline). Compute centroid; preserve framing within target
bbox (centred or rule-of-thirds per layout slot).

## Background regeneration vs outpaint

| Aspect change | Strategy |
|---|---|
| Same area, different ratio (mild) | outpaint into new dims |
| Significantly different (e.g. landscape → portrait) | regenerate full bg with same prompt + new dims |
| Same prompt yielded too-different result | iterate up to 2 times before falling back to crop+blur extension |

Re-generation preserves the original prompt, model, and style lock; only
target dims change.

## Text reflow

Text layer constraints in target bbox:
- Try same font, same size: fits → done
- Try shrinking by 5%, then 10%, ... down to 80% of original
- Try alternate alignment (center → left if width tight)
- Last resort: enable hyphenation, increase max_lines
- Reject if final fit needs > 30% font shrink → require user input

## Multi-target batch

```
def smart_resize_batch(page, targets: tuple[ResizeTarget, ...]) -> tuple[Page, ...]:
    # process targets in parallel where possible
    return tuple of N new Pages
```

## Standard target sets

| Set name | Targets |
|---|---|
| `social_kit` | IG square (1080×1080), IG story (1080×1920), FB cover (1640×856), LinkedIn header (1584×396), TikTok (1080×1920), X post (1200×675) |
| `print_kit` | A2, A3, A4, US Letter, Tabloid (all at 300 DPI) |
| `book_companion_set` | full book + cover thumbnail + banner + social posts |

User picks from named sets or composes custom.

## API surface

| Action | Args | Returns |
|---|---|---|
| `smart_resize` | `page_id, target_size_px, [strategy]` | new Page (versioned) |
| `smart_resize_batch` | `page_id, targets: ResizeTarget list` | tuple[Page, ...] |
| `target_set_apply` | `document_id, set_name, [page_id]` | tuple[Document, ...] (one per target) |
| `resize_preview` | `page_id, target_size_px` | thumbnail (no commit) |

## Edge cases

1. **Page with mostly text** (e.g. infographic flow) — resize works mainly
   on layout reflow; little generative cost.
2. **Page with multiple subjects** — preserve all; if target too narrow,
   warn that some subjects will overlap or be cropped.
3. **Logo doesn't fit corner** — scale logo down to ≥ 24px min; if still
   too small, warn.
4. **Aspect change so extreme that subject is inevitably cropped** —
   warn user; recommend regenerate strategy.
5. **Text shrink > 30%** — abort with `SmartResizeTextOverflowError`; user
   must choose: shorter copy, smaller layer, or crop.
6. **Brand kit colour falls into bg regeneration** — pass kit palette into
   regen prompt to maintain colour consistency.
7. **Target set spans multiple aspect ratios with large jumps** — process
   cluster-by-cluster; share regenerated bgs where ratios are similar.
8. **Strategy=STRETCH on > 20% aspect diff** — warn explicitly; this is
   "use only if you know what you're doing".

## Errors

- `SmartResizeTextOverflowError(ConfigError)`
- `SmartResizeTargetInvalidError(ConfigError)`
- `SmartResizeBackendError(ToolError)` — gen failure cascade

## Test surface

- Unit: subject framing math; text fit search; layer role classification.
- Integration: portrait → square smart resize preserves subject centring;
  text reflow keeps content readable; background regen invoked when aspect
  diff > threshold.
- Property: smart_resize is idempotent when target == source dims.
- Performance: full social_kit (6 targets) on a single page < 30 s with
  shared bg regens.

## Dependencies

- §03 mask system (subject detection)
- §04 generative (regenerate, outpaint)
- §05 text (reflow logic)
- §06 shapes (scale primitives)
- §10 layouts (slot rules)
- §23 versioning (diff capture per resize)
