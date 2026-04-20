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

### Runtime + integration (Tranche 5 — built directly; specced retroactively)

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 13 | [`journal.md`](./journal.md) | Multi-resolution narrative: today / yesterday / week / month / recent-history. Progressive LLM summarization at each level. Identity refresh on WISDOM change. | 1, 8 |
| 14 | [`working-memory.md`](./working-memory.md) | Operator base prompt (immutable to self) + self-managed working memory (bounded scratch space). WM maintenance loop is a P13 RASO producer. | 1, 8, 9 |
| 15 | [`rss-thinking.md`](./rss-thinking.md) | Four progressive levels per RSS item: weak summary always, WM entry on notable, OPINION on interesting, AFFIRMATION + scheduled action on commit. | 1, 2, 4, 9, 14, 18 |
| 16 | [`semantic-retrieval.md`](./semantic-retrieval.md) | Embedding-based search across durable + stance-bearing memory. Score = similarity × weight. I_DID-only by default. | 1, 6, 8, 19 |
| 17 | [`chat-surface.md`](./chat-surface.md) | OpenAI-compatible HTTP. Streaming for plain replies, non-streaming when tools fire. Per-user session tagging via upstream auth header. Cluster does auth. | 9, 14, 16, 18, 19 |
| 18 | [`tool-layer.md`](./tool-layer.md) | ToolRegistry allowlist, OpenAI function-call schemas, failure → stance OPINION. Obsidian + RSSReader real; Wiki/WP/Search/Newsletter scaffolded. | 1, 4, 17 |
| 19 | [`litellm-provider.md`](./litellm-provider.md) | Single LiteLLM proxy + virtual key. Pools = (model, free-tier window, role). complete + embed + quota_window in one Provider Protocol. | 8 |
| 20 | [`runtime-reactor.md`](./runtime-reactor.md) | Blocking-tick + ThreadPoolExecutor side channel. Deliberate divergence from main's asyncio. FakeReactor for tests. | — |
| 21 | [`observability.md`](./observability.md) | v1 Prometheus metric contract. Inspect CLI read-only subcommands. Smoke mode acceptance criteria. | all |

### Self-model (Tranche 6 — durable content of the autonoetic self)

The self-model — what the Turing Conduit knows about itself between requests — above and beyond episodic memory. Companion overview at [`../autonoetic-self.md`](../autonoetic-self.md).

| # | Spec | Scope | Depends on |
|---|---|---|---|
| 22 | [`self-schema.md`](./self-schema.md) | Tables and value types for all self-model nodes: personality facets, passions, hobbies, interests, preferences, skills, todos, mood, activation contributors. | 1, 2 |
| 23 | [`personality.md`](./personality.md) | HEXACO-24 profile. Random bootstrap draw, 200-item HEXACO-PI-R seed, weekly 20-item re-test weighted by time-since-last-asked, narrative revision via the activation graph. | 22 |
| 24 | [`self-nodes.md`](./self-nodes.md) | Passions, hobbies, interests, preferences, skills. Bootstrap-empty, accrete via self-authored `note_*` tools. Skill decay applied on read: `level × exp(-rate × days)`. | 22 |
| 25 | [`activation-graph.md`](./activation-graph.md) | Contributor edges (`target, source, weight, origin, rationale`). `active_now(node) = sigmoid(Σ weight × source_state / SCALE)`. Origins: self / rule / retrieval (TTL-bounded). Conflict via counter-contributors. | 22, 23, 24 |
| 26 | [`self-todos.md`](./self-todos.md) | Self-authored todos with required `motivated_by_node_id`. Append-only revision history. Completion mints AFFIRMATION + reinforces motivator via a contributor edge. | 22, 24 |
| 27 | [`mood.md`](./mood.md) | `(valence, arousal, focus)` singleton. Hourly decay toward neutral; event nudges (tool success/fail, AFFIRMATION/REGRET mints, todo completion, Warden alerts). Phase-1: affects tone only. | 22, 2 |
| 28 | [`self-surface.md`](./self-surface.md) | Self-tool registry, `recall_self()` deep read, 4-line minimal prompt block (identity + mood + active todos + dominant passion). First-person framing throughout. | 22, 23, 24, 25, 26, 27 |
| 29 | [`self-bootstrap.md`](./self-bootstrap.md) | `stronghold bootstrap-self` CLI. Random HEXACO draw → 200 Likert LLM answers with justifications → 24 facets + 1 mood + empty everything else. Idempotent per `self_id`; resumable. | 22, 23, 24, 27, 8 |
| 30 | [`self-as-conduit.md`](./self-as-conduit.md) | First-person routing pipeline: Warden → minimal block + retrieval contributors → perception (LLM + possible `recall_self`) → decision (`reply_directly` / `delegate` / `ask_clarifying` / `decline`) → dispatch → observation (self-model updates, mood nudges). Replaces the stateless Conduit for the Turing branch. | 22, 23, 24, 25, 26, 27, 28, 29, 9, 16, 17 |

## Deferred

- **Additional detectors** — `learning_extraction`, `affirmation_candidacy`, `prospection`. Pattern is established by `detectors/contradiction.md`; individual specs will land alongside implementations.
- **Self naming** — the self starts unnamed; operator-settable or self-chosen via reflection. Tool and policy not yet specified.
- **Mood affects decisions** — Phase-2 coupling of mood to routing / model choice / Warden thresholds. Specified as deferred in [`mood.md`](./mood.md) Q27.4.

## Non-goals (all specs)

- Multi-tenant scoping.
- Per-user memory.
- Backward compatibility with `src/stronghold/memory/`.
- Production deployment.

## Lineage

The 7-tier memory model originated in CoinSwarm (begun November 2025) and crystallized January 15, 2026. Stronghold imported it March 25, 2026. Project Turing's extension to durable personal memory follows from that research line; see [`../DESIGN.md`](../DESIGN.md) for the full thesis and Tulving-taxonomy mapping.
