# AgentTuring — v1.0 ROADMAP

**Dominant constraint:** continuity of self.
**Horizon:** 3 months from PR merge (per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md)).
**v1.0 definition:** self-consistency-as-tests — autonoesis is *measurable* via property tests asserting "the same self that started the run finishes it."

This document is the v1.0 source of truth. The legacy [`ROADMAP.md`](ROADMAP.md) (~36KB, inherited from the stronghold mirror) covers the broader Stronghold roadmap and is being progressively migrated; treat conflicts in favor of this document until the migration completes.

## v1.0 acceptance — the autonoetic property tests

At v1.0 merge, the Conduit must pass these Hypothesis property tests over a 30-day continuous run, with no human intervention beyond restarts:

### 1. Identity continuity

```
FOR ALL pairs of restarts (r1, r2) within the run:
  selfmodel_at(r1).identity_hash == selfmodel_at(r2).identity_hash
  selfmodel_at(r1).hexaco_24 ≅ selfmodel_at(r2).hexaco_24       (≤ 0.05 L₂ drift weekly retest)
  selfmodel_at(r1).passions ⊇ long_lived_passions               (decay-aware)
```

### 2. Narrative consistency

```
GIVEN any prior episode E recorded as REGRET, AFFIRMATION, or WISDOM
WHEN the Conduit is asked "what happened in E?"
THEN the answer references the same actors, the same outcome, and the same self-attribution
     across at least 3 independent recall sessions on different days
```

### 3. Decision provenance

```
FOR EVERY self-authored todo T:
  T.provenance is non-empty and points to an episodic memory M
  M.tier in {LESSON, REGRET, AFFIRMATION, WISDOM}
  T.activation_edges trace back to M via the activation graph
```

### 4. Mood plausibility

```
FOR EVERY 1-hour window W:
  |mood_at(W.end) - mood_at(W.start)| ≤ mood.max_delta_per_hour
  mood_at(W.end) is bounded by recent_inputs(W) within tolerance
  no mood field is NaN or unbounded
```

### 5. Memory floor preservation

```
FOR EVERY memory M with tier == REGRET and weight ≥ 0.6:
  M is retrievable at any point in the 30-day run
  decay(M, t) ≥ 0.6 for all t in [t_create, t_create + 30 days]
```

## Required substrate work

These engine pieces must land before the v1.0 property tests can pass:

| Engine artifact | Purpose | Status |
|---|---|---|
| [`engine#ADR-036`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-036-ontology-semantic-object-layer.md) | `SelfModel`, `Mood`, `Drive` registered as ontology entities | Accepted; `gap-impl` |
| [`engine#ADR-034`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-034-memory-canonical-ownership.md) | Memory protocols Turing builds on | Accepted |
| [`engine#ADR-037`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-037-observability-taxonomy.md) | Behavioral inspection via Langfuse | Accepted |
| [`engine#ADR-038`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-038-reliability-taxonomy.md) | Reliability primitives Turing's continuous run depends on | Accepted |

## Non-goals for v1.0

- **Multi-tenancy.** AgentTuring is single-self by definition. Multi-tenant work belongs in `stronghold`.
- **Self-hosted prosumer UX.** Belongs in `Project_mAIstro`.
- **Production deployment.** This is an experimental product; v1.0 is the demonstration that autonoesis is achievable, not that it is operable at scale.
- **RASO meta-agent.** The self-modifying graph layer is a v1.2+ research direction; the inner feedback loop suffices for v1.0.
- **Tournament-based evolution at runtime.** Scaffolding only; not wired to production routing in v1.0.

## Workstreams

### W1 — Self-model substrate (weeks 1–4)

- Implement `OntologyEntity` for `SelfModel`, `Mood`, `Drive` per `engine#ADR-036`
- HEXACO-24 weekly re-test runner with drift-bound assertion
- Mood vector with decay curve and bounded delta
- Drive store with reinforcement and decay

### W2 — Episodic memory + provenance (weeks 2–6)

- 7-tier memory implementation (substrate: `engine#ADR-016`, `engine#ADR-017`)
- Weight floors enforced for REGRET (≥0.6) and WISDOM (≥0.9)
- Activation graph wiring with self-authored edges
- Todo → episode provenance enforcement

### W3 — Self-talk loop (weeks 3–7)

- Continuous self-talk loop (no human input required)
- Awareness loop hz tunable per `engine#ADR-033` template knob
- Memory consolidation job at idle
- Dossier generation

### W4 — Self-consistency property tests (weeks 6–10)

- Property tests 1–5 above implemented as Hypothesis specs
- 30-day staging run with all five tests asserted
- Failure analysis and triage
- v1.0 acceptance gate

### W5 — Polish (weeks 9–12)

- Reading-order docs aligned with Copier template
- ARCHITECTURE.md autonoetic-only (strip enterprise content)
- Bootstrap into `engine/templates/autonoetic/` per [`engine#ADR-033`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-033-templates-and-copier-workflow.md)

## Risks and unknowns

- **HEXACO drift bound (0.05 L₂ weekly).** This number is a guess. The first weekly re-tests in W1 calibrate it. If real drift exceeds the bound under no-stress conditions, the bound is wrong, not the implementation.
- **Narrative consistency across recall sessions.** LLMs reconstruct, they don't replay. The test asserts agreement on actors/outcome/attribution; phrasing is not gated. If this turns out to be too lax (Conduit confabulates differently each time but happens to match on tokens), the test gets tightened in W4.
- **Memory floor enforcement under decay drift.** The 0.6 weight floor for REGRET assumes decay never reaches that low for retained items. If the decay curve is mis-tuned, the floor catches it; the test is the safety net.
- **30-day continuous run with no human intervention.** Depends on `engine#ADR-038` reliability primitives being in place. If circuit breakers fire repeatedly, the run is invalid; that's a feature, not a bug.

## v2.0 horizon (12 months, inventory-clear)

- RASO meta-agent (self-modifying activation graph)
- Tournament evolution wired to production routing
- Lineage: Conduit can answer "what did you used to think about X?" with snapshots
- Cross-self portability (export self-model into a fresh Conduit and have it remain *the same self*)
- Phantom execution and dream loop

These are deliberately deferred. v1.0 demonstrates autonoesis exists; v2.0 explores what it can do.
