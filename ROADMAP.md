# AgentTuring — ROADMAP

**Role:** autonoetic experimental product (per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md)).
**Dominant constraint:** continuity of self.
**Horizon:** v1.0 at 3 months; v2.0 at 12 months (inventory-clear).
**v1.0 acceptance:** five Hypothesis property tests pass over a 30-day continuous run (see [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) for the test plan).

## What this roadmap is

The **full** AgentTuring roadmap. Items are tagged with their owning repo:

- `[turing-NNN]` — work that lives in this repo
- `[engine#engine-NNN]` — substrate work in `maistro-engine` that this product depends on
- `[sh#sh-NNN]` — cross-product work in `stronghold` (rare; only where an A2A or engine-template change affects Turing)

[`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) is the v1.0 source of truth and the workstream / property-test detail. This file is the longer horizon plus per-version itemisation.

## Replaces

This ROADMAP supersedes the previous `ROADMAP.md` (~36KB, blob-identical to `agent-stronghold/stronghold` at the time of the four-repo split). That content described Stronghold's build phases and is preserved in stronghold's repo where it belongs.

## v1.0 — measurable autonoesis (3 months)

### M1 — Self-model substrate (weeks 1–4)

- `[turing-001]` HEXACO-24 personality + weekly re-test runner + drift-bound assertion
- `[turing-002]` Mood vector with decay curve + bounded delta
- `[turing-003]` Drive store with reinforcement and decay
- `[turing-004]` `SelfModel`, `Mood`, `Drive` registered as ontology entities
- Depends on `[engine#engine-030]` Ontology Semantic facet shipped

### M2 — Episodic memory + provenance (weeks 2–6)

- `[turing-010]` 7-tier memory implementation (OBSERVATION → WISDOM)
- `[turing-011]` Weight floors enforced for REGRET (≥ 0.6) and WISDOM (≥ 0.9)
- `[turing-012]` Activation graph with self-authored edges
- `[turing-013]` Todo → episode provenance enforcement
- Depends on `[engine#ADR-016]` episodic-store, `[engine#ADR-017]` outcome-store

### M3 — Self-talk loop (weeks 3–7)

- `[turing-020]` Continuous self-talk loop runs without human input
- `[turing-021]` Awareness loop hz tunable per Copier knob (`engine#engine-011`)
- `[turing-022]` Memory consolidation job at idle
- `[turing-023]` Dossier generation

### M4 — Self-consistency property tests (weeks 6–10)

- `[turing-030]` Identity continuity property test
- `[turing-031]` Narrative consistency property test
- `[turing-032]` Decision provenance property test
- `[turing-033]` Mood plausibility property test
- `[turing-034]` Memory floor preservation property test
- `[turing-035]` 30-day staging run with all five tests asserted
- Depends on `[engine#engine-038]` reliability primitives (so the run itself is stable)

### M5 — Polish + bootstrap (weeks 9–12)

- `[turing-040]` Reading-order docs aligned with template knob set
- `[turing-041]` Strip Stronghold-only content from `ARCHITECTURE.md`, `BACKLOG.md`, `src/`
- `[turing-042]` Migrate the 31 `ADR-K8S-*` records out of this repo to stronghold (see `[sh#sh-020]`)
- `[turing-043]` Bootstrap into `engine/templates/autonoetic/` per `[engine#engine-011]`

## v1.1 — the autonoetic stack hardens (3–6 months)

- `[turing-050]` Lineage queries: "what did you used to think about X?" returns a tracked snapshot
- `[turing-051]` Dream loop (offline replay + consolidation; ports `Project_mAIstro#S-025` if applicable)
- `[turing-052]` Phantom execution: the self can simulate a route without committing
- `[turing-053]` Adversarial hardening of the self-model (substrate-agnostic; consumes `[engine#engine-038]` chaos primitives if shipped)

## v1.2 — RASO inner loop formalised (6–9 months)

- `[turing-060]` `epic-13-hyperagents-meta-level` formalised as Turing-specific RASO
- `[turing-061]` Auditor → Mason → extract → store → track inner cycle wired to Turing's self-talk
- `[turing-062]` Tournament-based agent evolution scaffolding wired to internal-only routing (no production traffic)
- Depends on `[engine#engine-051]` Forge iteration loop primitive (if generalised)

## v1.3 — RASO meta-agent (9–12 months)

- `[turing-070]` Meta-agent that modifies Turing's activation graph structure
- `[turing-071]` Parameter-sensitivity learner: which knobs to turn by inches, which by leaps
- `[turing-072]` Self-modifying graph runs against the property tests; if any test fails, the modification is rejected

## v2.0 — cross-self portability (12+ months)

- `[turing-080]` Export self-model into a fresh Conduit; the imported self answers consistency tests as the same self
- `[turing-081]` Long-horizon recall ("do you remember the day in M2 when…") with confidence calibration
- `[turing-082]` Mood + drives synthesised from imported episodic record (if a self is imported with no live mood)
- `[turing-083]` Confidence-calibrated routing: classifier uncertainty → model tier (substrate piece if it generalises)

## Non-goals (for any AgentTuring version)

- **Multi-tenancy.** Owned by `stronghold`. Turing is single-self by definition.
- **Self-host UX.** Owned by `Project_mAIstro`.
- **Production deployment.** Turing is an experimental product. v1.0 is the demonstration that autonoesis is achievable, not that it is operable at scale.
- **K8s topology.** Owned by `stronghold`; the 31 `ADR-K8S-*` records currently in this repo migrate out per `[turing-042]` and `[sh#sh-020]`.
- **Compliance frameworks (OWASP / NIST / EU AI Act).** Owned by `stronghold`. Turing is not a compliance target.

## Cross-repo dependency map

Critical engine items Turing v1.0 needs:

| Engine item | Turing item(s) it unblocks |
|---|---|
| `[engine#engine-001]` Registry CI | front-matter on Turing specs (`turing-090`) |
| `[engine#engine-011]` Copier autonoetic template | bootstrap (`turing-043`) |
| `[engine#engine-030]` Ontology Semantic facet | self-model registration (`turing-004`) |
| `[engine#engine-031]` Observability primitives | self-talk loop instrumentation (`turing-020`) |
| `[engine#engine-032]` Reliability primitives | 30-day continuous run stability (`turing-035`) |
| `[engine#engine-021]` Memory spec dedup | `turing-dossier`, `turing-memory-consolidator` recast (`turing-091`) |

## Progress dashboard

Updated 2026-05-07 (manual; will be regenerated by registry CI once `[engine#engine-001]` lands):

```
v1.0 M1 Self-model substrate     [·] ░░░░░░░░░░   0%   Pending engine ontology (engine-030)
v1.0 M2 Episodic + provenance    [~] █████░░░░░  50%   7-tier memory + weight floors live; activation graph + provenance pending
v1.0 M3 Self-talk loop           [~] ███░░░░░░░  30%   `turing-self-talk-loop.yaml` spec exists; impl is a runnable sketch
v1.0 M4 Property tests           [·] ░░░░░░░░░░   0%   Specified in ROADMAP-v1.0.md; not yet written
v1.0 M5 Polish + bootstrap       [·] ░░░░░░░░░░   0%   Pending engine template (engine-011)
```

Legend: `[x]` complete | `[~]` in progress | `[·]` not started

## Maintenance

- New items get appended; status changes happen in-place.
- IDs are stable. Items never get renumbered.
- Items shipped get `Implemented` in [`BACKLOG.md`](BACKLOG.md) with the PR linked.
- This file and `BACKLOG.md` are the AgentTuring-side coordination surface; engine work it depends on lives in `engine#BACKLOG.md`.
