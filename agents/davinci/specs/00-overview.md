# 00 — Overview

## Goals

Da Vinci should produce **print-ready** and **screen-ready** deliverables for:

1. **Children's books** — picture books, early readers, board books. Cover + interior
   spreads. Consistent character + style across all pages.
2. **Posters** — events, movies, info, propaganda-style. Single-page, large format,
   strong typographic hierarchy, print-ready bleed.
3. **Infographics** — data-driven layouts with real charts, icons, connectors,
   multi-section composition. Often shared as PNG/PDF posters.
4. **Reach goal**: video overlays + video edits (titles, captions, lower-thirds,
   simple cuts, AI-generated b-roll).

## Non-goals (explicit)

- **Not Inkscape** — no node-level vector editing, no boolean path UI, no curve
  handles. The agent emits geometry; the runtime renders it.
- **Not Photoshop** — no advanced photo retouching (frequency separation,
  channel mixing, dodge & burn brushes). A useful subset is supported (§07) but
  the use cases above don't need a full photo lab.
- **Not Figma** — no real-time multi-cursor collaboration. Single-author,
  multi-tenant.
- **Not a video NLE** — the reach goal is overlays + simple cuts + AI gen, not
  Premiere/DaVinci Resolve parity.
- **Not a UI** — Da Vinci is the operator. A frontend may exist later, but every
  feature must be agent-callable first.

## Success criteria

For each use case, "shipped" means:

| Use case | Success means |
|---|---|
| Picture book | 32-page book, consistent character across all pages, print-ready PDF with bleed, ePub optional |
| Early reader | 64-page chapter book, body text auto-paginated, drop caps, spot illustrations |
| Movie poster | 24×36" @ 300 DPI, CMYK, vector text, layered design exportable as flat PDF |
| Infographic | A2 single-page with ≥3 chart types from a CSV input, branded palette, exportable as PDF + SVG |
| (Reach) Read-along video | Book → narrated MP4 with synchronized captions, page-turn animation |

## Glossary

| Term | Meaning |
|---|---|
| **Document** | Top-level container: 1..N Pages with shared brand kit + style lock |
| **Page** | Single canvas with print spec (size, bleed, safe area) and layered content |
| **Layer** | One element on a page: raster source, vector source, text, shape, group |
| **Effect** | Non-destructive operation in a Layer's effect stack (e.g. brightness, blur) |
| **Mask** | Greyscale alpha defining where an effect or generative op applies |
| **Style lock** | Cross-page art-direction constraint (palette, rendering, line weight) |
| **Brand kit** | Tenant-/user-scoped palette + fonts + logos applied to a Document |
| **Print spec** | Trim size, bleed, safe area, DPI, color mode for press output |
| **Spread** | Two facing pages in a book (verso + recto) |
| **Master page** | Reusable layout inherited by other pages |

## Threat model deltas (vs. existing canvas tool)

New surfaces, all routed through existing Warden + Sentinel:

1. **Uploaded source images** (book pages, references, brand assets) — Warden
   scan for prompt-injection-in-image (visible text on images can carry
   instructions). Existing `upload` action; tighten to require Warden pass.
2. **Charts from user-supplied data** — CSV/JSON input is untrusted. Sentinel
   validates schema, bounds, no formula injection (Excel-style `=…`).
3. **Custom font upload** — TTF/OTF can carry executable hinting. Whitelist
   subset of font tables; reject unknown. Bandit-equivalent for fonts.
4. **Multi-tenant template marketplace** (P2) — user-shared templates ship at
   trust tier T3 by default; admin promotion required for T2+.
5. **Stored documents** — every persistence query MUST filter by `tenant_id`.
   Audit log every read of cross-tenant-shared assets (brand kit, template).
6. **Print metadata leakage** — exported PDF must NOT embed user/tenant IDs in
   metadata unless explicitly opted in.

## Roadmap (compressed)

| Phase | Subsystems | Days |
|---|---|---|
| 1 — Foundation | 01, 02, 08 | 10 |
| 2 — Doc & layout | 02, 10, alignment | 9 |
| 3 — Type & vector | 05, 06, icons | 7 |
| 4 — Generative parity | 03, 04, 09 | 9 |
| 5 — Infographic-specific | 12, 07 minimum | 6 |
| 6 — Templates & output | 11, 13, 14 | 9 |
| **Static total** | | **~50** |
| Reach | 15 | ~30 |

Cumulative: ~10 weeks for static, +6 weeks for video reach.
