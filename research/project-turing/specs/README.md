# Project Turing — Specs

Individually reviewable specs for the durable personal memory layer. Each spec owns its acceptance criteria and its implementation guidance. Specs are small on purpose; a reviewer should be able to hold one in mind at once.

**Branch:** `research/project-turing` (research only; not for `main`).
**Parent doc:** [`../DESIGN.md`](../DESIGN.md).

---

## Specs in this directory

Read in order. Later specs depend on earlier ones.

### Memory layer (Tranche 1 — buildable today)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 1 | [`schema.md`](./schema.md) | Field additions to `EpisodicMemory`; the `SourceKind` enum. | — |
| 2 | [`tiers.md`](./tiers.md) | Add `ACCOMPLISHMENT`. Revised 8-tier set with weight bounds and inheritance priority. | 1 |
| 3 | [`durability-invariants.md`](./durability-invariants.md) | The eight invariants enforced for REGRET, ACCOMPLISHMENT, WISDOM. | 1, 2 |
| 4 | [`write-paths.md`](./write-paths.md) | Write triggers and actions for REGRET, ACCOMPLISHMENT, AFFIRMATION. | 1, 2, 3 |
| 5 | [`wisdom-write-path.md`](./wisdom-write-path.md) | WISDOM invariants (consolidation-origin only, I_DID provenance, traceable lineage, no superseding WISDOM). Write path defined in `dreaming.md`. | 1, 2, 3, 12 |
| 6 | [`retrieval.md`](./retrieval.md) | Reserved quota, source-filtered views, lineage-aware retrieval. | 1, 2, 3 |
| 8 | [`persistence.md`](./persistence.md) | `durable_memory` table, version migration, `self_id` minting. | 1, 2, 3 |

### Motivation and dispatch (Tranche 2 — needs scheduling primitive)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 9 | [`motivation.md`](./motivation.md) | Priority ladder (P0=1M … P70=0.01), pressure vector, fit vector, scoring formula, backlog, two loops, dispatch contract. | 1, 2, 3, 4 |
| 10 | [`scheduler.md`](./scheduler.md) | P0 scheduled-delivery work. Early-executable window, held-for-delivery, 5x-dream-time quiet zones. | 9 |
| 7 | [`daydreaming.md`](./daydreaming.md) | Per-model candidate producer of last resort. I_IMAGINED writes only; cannot reach durable tiers. Priority is f(pressure). | 1, 2, 3, 6, 9 |

### Tuning and detectors (Tranche 3 — observation feed + first detector)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 11 | [`tuning.md`](./tuning.md) | Runtime coefficient adjustment. Observations → tuner candidates → AFFIRMATION commitments. | 1, 4, 9 |
| D | [`detectors/README.md`](./detectors/README.md) | Detector pattern: cheap watchers that propose backlog candidates. | 9 |
| D.1 | [`detectors/contradiction.md`](./detectors/contradiction.md) | Worked example — detects contradictory durable memories with a known resolution; proposes a LESSON-minting candidate. | 1, 3, 4, 9, D |

### Dreaming (Tranche 4 — consolidation and WISDOM)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 12 | [`dreaming.md`](./dreaming.md) | Scheduled consolidation. Seven phases: pattern extraction, WISDOM candidacy, AFFIRMATION proposal, LESSON consolidation, non-durable pruning, review gate, session marker. Sole write path into WISDOM tier. | 1, 2, 3, 4, 9, 10 |

## Deferred

- **Additional detectors** — `learning_extraction`, `affirmation_candidacy`, `prospection`. Pattern is established by `detectors/contradiction.md`; individual specs will land alongside implementations.

## Non-goals (all specs)

- Multi-tenant scoping.
- Per-user memory.
- Backward compatibility with `src/stronghold/memory/`.
- Production deployment.

## Lineage

The 7-tier memory model originated in CoinSwarm (begun November 2025) and crystallized January 15, 2026. Stronghold imported it March 25, 2026. Project Turing's extension to durable personal memory follows from that research line; see [`../DESIGN.md`](../DESIGN.md) for the full thesis and Tulving-taxonomy mapping.
