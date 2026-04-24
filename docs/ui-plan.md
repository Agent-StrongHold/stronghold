# UI Plan — Turing's Field Console

**Status:** authoritative UI plan for Stronghold's operator console, superseding the UI portions of `ROADMAP.md` and `BACKLOG.md` (UI bullets only; non-UI bullets in those docs are unaffected).

**Scope:** the handler-facing admin console for Agent Turing. Six surfaces, one design system, one React shell. Turing is the first agent that gets the console; the Phosphor/Noir system is the design foundation for any agent-level console that follows.

**Companion spec index:** [`specs/TURING-CONSOLE-README.md`](../specs/TURING-CONSOLE-README.md) lists every spec (backend + frontend) and the implementation order.

---

## Point of view

Everything is **handler POV** — the operator console, not the agent's perspective. The handler reads, inspects, edits, publishes. The agent (Turing) writes to its own notebook, ships posts to its own blog, and updates its own dossier through the self-model tools on `research/project-turing`; the console exposes those artifacts to the handler without becoming the agent's own UI.

---

## The six surfaces

| # | Surface | Route | Backs |
|---|---------|-------|-------|
| 1 | **Chat** | `/dashboard/chat` | Spec 1182 — SSE streaming, typewriter reveal, inline memory citations, daily initiation budget, Turing-initiated thread marker |
| 2 | **Notebook** | `/dashboard/notebook` | Spec 1183 — live vault API over the Obsidian store; file tree, editor, backlinks, graph view; six canonical sections (daily / scratchpad / outbox / art / self-todo / passions) |
| 3 | **Blog** | `/dashboard/blog` (handler preview) + installed WordPress theme (public) | Spec 1179 — handler preview component + installable `phosphor-noir` FSE block theme shipped into `wp-content/themes/` for Turing's public blog |
| 4 | **Dossier** | `/dashboard/dossier` | Spec 1184 — bio + versioned autobiography + 5-facet personality dials (read-only by default per audit F9/F10) + operator settings + read-only vitals |
| 5 | **Synapse** | `/dashboard/synapse` | Spec 1181 — 7-tier DB inspector; tier nav, row list, row detail/edit, promote/demote/expire/burn, audit-flag surfaces (F1/F4/F13/F18) |
| 6 | **Skills Lab** | `/dashboard/skills-lab` | Spec 1185 — thin console over Forge + SkillRegistry; list, request, review, promote (skull → T3 → T2 → T1), demote, burn |

---

## Phosphor/Noir — the design system

Dark-mode retrofuturist noir. Greys to whites. CRT phosphor green primary. 1960s IBM-manual typography. The reference prototypes live in the Claude Design bundle at <https://api.anthropic.com/v1/design/h/Ep6F75A8GJNtWBrIKNDIdw> — spec 1187 (frontend port) pins the exact tokens the port must match.

### Color

- **Ink / Bone greyscale** — `--ink-0` (#050507) through `--ink-5` (#222825); `--bone-0` (#F2F0EA) warm white for headings; `--bone-1` (#ECEAE3) body.
- **Signal: phosphor green** — `--phosphor` (#5EE88C) default, `--phosphor-hi` (#A8FF8E) highlight, `--phosphor-dim` (#1E7A3D) recess. Glow tokens: soft / med / hot.
- **Amber** — `--amber` (#FFB547) for classified / warning chrome (e.g. `[ CLASSIFIED · HANDLER EYES ONLY ]`).
- **Burn** — `--burn` (#FF5A4E) for destructive actions (burn-skill, burn-memory).

### Type

- **VT323** — display face, big retro-phosphor moments (h1, hero classification bars).
- **IBM Plex Mono** — default UI mono (labels, IDs, tags, buttons).
- **IBM Plex Sans** — UI body.
- **IBM Plex Serif** (italic) — narrative body (Turing's writing, dossier bio, field reports).

### Chrome

- Topbar: project mark (◆), breadcrumb, UTC clock, wire status.
- Classification banner (amber, uppercase, `0.32em` tracking).
- Section labels (dashed-rule flanked, mono, `0.22em` tracking).
- Cards: `1px` solid `--line-2` border, `--ink-2` background, phosphor border on hover with `0 0 22px rgba(94,232,140,.18)` glow.
- CRT overlay (optional, toggleable): scanlines + grain + soft vignette from `styles/crt.css`.

---

## Two-tier memory surface boundaries

The console realises the two-tier memory architecture on the write side:

| Surface | Reads | Writes |
|---------|-------|--------|
| Notebook | Obsidian vault (markdown, working memory) | Handler PUT/POST → ObsidianStore (audit-logged, Warden-scanned) |
| Synapse | 7-tier vector DB (persistent recall) | Handler PATCH/POST → EpisodicMemoryStore / LearningStore (audit-logged, Warden-scanned, admin-only) |

The Consolidator (spec 1180) is the only path that crosses from working → persistent. Source notes are never deleted.

---

## Renames at port time

The design bundle uses earlier surface names that the specs have since renamed. The frontend port must apply these consistently:

- **Memory → Synapse** — `Memory.html` / `memory.jsx` / `/api/memory/*` → `Synapse.html` / `synapse.jsx` / `/api/synapse/*`. Permission name: `memory_crud` → `synapse_crud`.
- **Profile → Dossier** — `Profile.html` / `profile.jsx` / `/api/profile/*` → `Dossier.html` / `dossier.jsx` / `/api/dossier/*`. *(The design bundle's Profile card subtitle already reads `◆ PR-03 · DOSSIER`.)*

The internal `src/stronghold/memory/` and `src/stronghold/memory/episodic/` packages keep their names — Synapse is the handler-facing surface name only.

---

## What the frontend port does (spec 1187)

1. Install the Phosphor/Noir design system: `colors_and_type.css` tokens, `crt.css` overlays, shared UI primitives, font imports.
2. Replace the castle-themed dashboard pages (Great Hall, Knights, Armory, Watchtower, Treasury, Scrolls) with the six Phosphor/Noir surfaces. Non-Turing dashboard files (login, auth, XP, leaderboard) are out of scope for this port and stay as-is.
3. Ship the two installable themes under `themes/`: `phosphor-noir` WordPress FSE block theme, `phosphor-noir` Obsidian theme.
4. Each surface renders against stub data that matches the shape of its backend spec. Backend PRs (1178–1186) then wire the real endpoints in without touching the ported scaffolding.
5. The design bundle URL is recorded in the spec's `reference_assets` block; implementers refetch it and pixel-match.

---

## Implementation order (from the README)

1. **PR 1 (this PR)** — Plan + specs only. Locks architecture. No code. *(Adds `docs/ui-plan.md` + spec 1187.)*
2. **PR 2 — Spec 1187 Frontend port.** Phosphor/Noir shell, six stub surfaces, two installable themes, castle-dashboard removal.
3. **PR 3 — Spec 1178 ObsidianStore.** Foundation.
4. **PRs 4–6 (parallelisable)** — 1179 WordPress · 1182 Chat streaming · 1184 Dossier.
5. **PR 7 — Spec 1183 Notebook live vault.** After 1178.
6. **PR 8 — Spec 1186 Self-talk loop.** After 1178.
7. **PRs 9–10 (parallelisable)** — 1181 Synapse CRUD · 1185 Skills Lab.
8. **PR 11 — Spec 1180 Memory consolidator.** Last.

Each PR lands green (pytest + ruff + mypy --strict + bandit).
