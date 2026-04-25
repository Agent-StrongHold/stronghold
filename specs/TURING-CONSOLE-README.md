# Turing Field Console — specs index

**Plan:** [UI Plan — Turing's Field Console](../docs/ui-plan.md). The plan is the authoritative UI plan for Stronghold and supersedes the UI portions of `ROADMAP.md` and `BACKLOG.md` (UI bullets only).

**Context:** `project_turing.research.md` (repo root) is the research narrative for the autonoetic self this console operates on. The `research/project-turing/` branch + the `project_Turing` branch carry that self-model's own specs and runtime; this console layer sits **above** the self-model — it does not modify the 7-tier memory, it gives the handler a surface to read/inspect/publish/edit the self's artifacts.

## The six surfaces, and the specs that back them

The console is six surfaces total: **Chat**, **Notebook**, **Blog**, **Dossier**, **Synapse**, **Skills Lab**. The specs below carve the backend slice plus the one-shot frontend port (1187).

| # | Spec | Surface | Realises |
|---|------|---------|----------|
| 1178 | [`turing-obsidian-store.yaml`](turing-obsidian-store.yaml) | Notebook (foundation) | ObsidianStore protocol + filesystem impl + fake + four tools (read/write/append/search). Working-memory substrate for self-talk and scratch reasoning. |
| 1179 | [`turing-wordpress-publishing.yaml`](turing-wordpress-publishing.yaml) | Blog | WordPressClient protocol + REST impl + `wordpress_publish` tool + bundled WP/MariaDB docker-compose services. Autonomous publishing. |
| 1180 | [`turing-memory-consolidator.yaml`](turing-memory-consolidator.yaml) | (cross-cutting) | Consolidator that promotes recurring patterns from Obsidian into the 7-tier store. Reuses the existing `LearningStore` auto-promote path; closes the two-tier memory loop. Depends on 1178. |
| 1181 | [`turing-synapse-crud-endpoints.yaml`](turing-synapse-crud-endpoints.yaml) | Synapse | API endpoints backing the Synapse surface: tier list, row detail, edit, promote/demote/expire/burn, audit-flag surfaces for F1/F4/F13/F18. |
| 1182 | [`turing-chat-streaming.yaml`](turing-chat-streaming.yaml) | Chat | SSE streaming endpoint, daily initiation budget (Turing-initiated threads ≤ 1/day), inline memory citations, typewriter reveal. |
| 1183 | [`turing-notebook-live-vault.yaml`](turing-notebook-live-vault.yaml) | Notebook | Handler-facing notebook API over Turing's Obsidian vault. Depends on 1178. |
| 1184 | [`turing-dossier.yaml`](turing-dossier.yaml) | Dossier | Bio + autobiography (versioned) + 5-facet personality dials (read-only by default per audit F9/F10) + operator settings + read-only vitals aggregation. |
| 1185 | [`turing-skills-lab.yaml`](turing-skills-lab.yaml) | Skills Lab | Thin console API over the existing Forge + SkillRegistry: list/request/review/promote/demote/burn. |
| 1186 | [`turing-self-talk-loop.yaml`](turing-self-talk-loop.yaml) | Notebook (proactive) | Reactor-driven background loop: periodic "anything to say to myself?" tick + Reactor-event triggers + strategy self-initiation. Warden-scanned, rate-limited, not chat-gated. Depends on 1178. |
| 1187 | [`turing-frontend-port.yaml`](turing-frontend-port.yaml) | (all six) | Frontend port: Phosphor/Noir design system + app shell + six stub surface pages + installable WordPress + Obsidian themes. Renames Memory → Synapse and Profile → Dossier at port time. No backend endpoints wired — stub data only; each backend spec swaps its stub for a live call. |
| 1188 | [`turing-blog-authoring.yaml`](turing-blog-authoring.yaml) | Blog | Rich post authoring layered on 1179: media pipeline (hero + inline images + SVG) with alt-text enforcement, Phosphor/Noir markdown dialect (callouts, figures, pullquotes, inline SVG, memory citations), five post templates (field report, letter-to-self, dossier entry, notebook excerpt, ASCII-art piece), preflight validation that gates publish. |

## What is NOT in these specs

- **Self-model tools** (`note_passion`, `write_self_todo`, `record_personality_claim`, activation-graph authorship). Those live in the `research/project-turing/` specs. The audit findings F1/F4/F13/F18 referenced by the Synapse surface originate there.
- **7-tier memory internals** (episodic/semantic/biographical/regret/affirmation/wisdom storage). Already implemented; the Synapse surface reads/writes through the existing `EpisodicMemoryStore` / `LearningStore` protocols.
- **Warden / Sentinel / Gate semantics.** Already implemented; the new tools and endpoints hook into the existing boundary layer, they do not redefine it.
- **Rename of the internal `memory/` / `episodic/` packages.** Memory-the-substrate keeps its current name; Synapse is the *handler-facing surface name* only.

## Two-tier memory architecture

The Turing console realises a two-tier split on the write side of memory:

| Tier | Substrate | Role | Write point |
|------|-----------|------|-------------|
| Working memory | Obsidian vault (markdown on disk) | Self-talk, scratch reasoning, drafts, dreams/hobbies/passions journaling. **One-member conversation** — Turing writes whenever they want, not just during chat turns. | `obsidian_append`/`obsidian_write` tools (from strategy loops) + self-talk loop (proactive, spec 1186) |
| Persistent recall | 7-tier vector DB (existing) | Authoritative long-term memory | Memory consolidator (spec 1180) — promotes recurring patterns from Obsidian; existing `LearningStore` extractor — promotes from tool history |

Obsidian is durable on disk but not authoritative. The consolidator decides what crosses over. Source notes are never deleted — Turing can reread raw thoughts and notice patterns the consolidator missed.

## Build-rule compliance checklist

Per CLAUDE.md §Build Rules, every spec above is constrained by:

- **No Code Without Architecture** — the UI plan + this README + the YAML specs are the architecture.
- **No Code Without Tests (TDD)** — each spec's `acceptance_criteria` become failing tests before implementation starts.
- **No Hardcoded Secrets** — WordPress credentials + Obsidian vault path come from env/config; all defaults are example values.
- **No Direct External Imports in Business Logic** — protocols in `src/stronghold/protocols/`, impls behind DI, never imported directly.
- **Every Protocol Needs a Noop/Fake** — `tests/fakes.FakeObsidianStore` and `tests/fakes.FakeWordPressClient` are acceptance criteria.
- **Security Review Gates** — per ARCHITECTURE.md §3.6; security-boundary specs (1179 WordPress, 1181 Synapse, 1185 Skills Lab promotion, 1186 self-talk writes) get a pre-merge review.
- **No Co-Authored-By Lines** — kept.

## Implementation order

1. **PR 1 (this one)** — plan + specs only. Locks architecture. No code.
2. **PR 2 — spec 1187 Frontend port.** Port the Phosphor/Noir HTMLs/CSS/JSX + remove the castle-themed Turing surfaces. Six stub pages render against JSON fixtures shaped like each backend spec's response. Ships the two installable themes (WordPress, Obsidian) verbatim from the design bundle.
3. **PR 3 — spec 1178 ObsidianStore** — foundation; nothing else works without it.
4. **PRs 4–6 (parallelisable)** — 1179 WordPress transport · 1182 Chat streaming · 1184 Dossier.
5. **PR 7 — spec 1188 Blog authoring** (after 1179; rich posts, media pipeline, markdown dialect, five templates, preflight validation, memory citations).
6. **PR 8 — spec 1183 Notebook live vault** (after 1178).
7. **PR 9 — spec 1186 Self-talk loop** (after 1178).
8. **PRs 10–11 (parallelisable)** — 1181 Synapse CRUD · 1185 Skills Lab.
9. **PR 12 — spec 1180 Memory consolidator** (last — needs real vault data to be meaningful).

Each PR lands green (pytest + ruff + mypy --strict + bandit).
