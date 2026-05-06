# Da Vinci — Books, Posters, Infographics (Spec Index)

**Use cases**: children's books, posters, infographics. **Reach goal**: video overlays + edits.

This index points to focused subsystem specs in `specs/`. Read in order; each
later doc assumes the data model from earlier docs.

## Foundation
- [00-overview.md](specs/00-overview.md) — goals, non-goals, glossary, threat model deltas
- [01-effect-stack.md](specs/01-effect-stack.md) — non-destructive effect pipeline on `Layer`
- [02-document-model.md](specs/02-document-model.md) — `Document` / `Page` / `Layer` data model + persistence

## Editor primitives
- [03-mask-system.md](specs/03-mask-system.md) — masks, selection, segmentation
- [04-generative.md](specs/04-generative.md) — inpaint, outpaint, controlnet, upscale
- [05-text.md](specs/05-text.md) — text upgrades (drop caps, callouts, paths)
- [06-shapes.md](specs/06-shapes.md) — vector primitives, connectors, speech bubbles
- [07-photo-ops.md](specs/07-photo-ops.md) — adjustments, filters, blend modes (P2 minimum)

## Use-case-specific
- [08-print-spec.md](specs/08-print-spec.md) — bleed, trim, safe area, CMYK, DPI
- [09-style-lock.md](specs/09-style-lock.md) — cross-page art-style consistency
- [10-book-layouts.md](specs/10-book-layouts.md) — picture book / early reader / cover layouts
- [11-templates.md](specs/11-templates.md) — templates + brand kits
- [12-charts.md](specs/12-charts.md) — Vega-Lite charts, tables, connectors

## Output & polish
- [13-export.md](specs/13-export.md) — PDF (print), SVG, PNG, JPG, PPTX
- [14-smart-resize.md](specs/14-smart-resize.md) — magic resize for posters, social variants

## Reach goal
- [15-video.md](specs/15-video.md) — timeline, keyframes, AI video, captions, render queue

## Quality bar (applies to every spec)
- mypy `--strict` clean
- ruff lint + format clean (E, F, W, I, N, UP, B, A, SIM, TCH)
- bandit medium severity, no findings
- Coverage ≥ 95% on all new modules
- Every behaviour has a Gherkin scenario in `specs/features/`
- Every type has unit tests for invariants, defaults, and edge cases
- Tenant isolation tested at every persistence boundary
