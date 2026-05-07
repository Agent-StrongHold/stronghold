# AgentTuring — BACKLOG

The queue of autonoetic-product work. Items are tagged with their owning repo:

- `[turing-NNN]` — work that lives in this repo
- `[engine#engine-NNN]` — substrate work in `maistro-engine` that this product depends on
- `[sh#sh-NNN]` — cross-product work in `stronghold` (rare)

Maintained per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md). Status follows [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md) lifecycle.

## Replaces

This BACKLOG supersedes the previous 56KB `BACKLOG.md` (blob-identical to stronghold's at the time of the four-repo split). That content was Stronghold-relevant and is preserved in stronghold's repo where it belongs.

## Status legend

| Marker | Meaning |
|---|---|
| Proposed | Open for discussion; not yet binding |
| Accepted | Decision binding; implementation may follow |
| Implemented | Decision shipped; production code matches |
| Blocked | A `blocked-by:` dependency is unmet |
| Abandoned | Decision deliberately not taken (kept for traceability) |

## Gap legend

| Marker | Meaning |
|---|---|
| `gap-spec` | No spec or ADR captures this decision yet |
| `gap-test` | Spec/ADR exists; no test (or test stub) covers it |
| `gap-impl` | Spec/ADR + test exist; production code does not match |

---

## v1.0 critical path

### M1 — Self-model substrate

**[turing-001] HEXACO-24 personality + weekly re-test — Proposed; `gap-impl` — v1.0 M1**
- HEXACO-24 questionnaire authored as the "weekly check-in" the Conduit performs on itself
- Re-test runs as a scheduled job; emits a `selfmodel.retest` event (per `engine#ADR-037`)
- Drift bound: weekly L₂ distance ≤ 0.05 under no-stress conditions; first month calibrates this number
- Tests: behavioral property test asserts drift bound (turing-030)

**[turing-002] Mood vector with decay + bounded delta — Proposed; `gap-impl` — v1.0 M1**
- Mood as a typed vector (e.g. PAD or HEXACO-aligned)
- Decay curve (configurable) + bounded delta per hour
- Reinforcement on outcome events
- No NaN, no unbounded values — enforced at the boundary

**[turing-003] Drive store with reinforcement and decay — Proposed; `gap-impl` — v1.0 M1**
- Drives = passions / hobbies / interests / skills / preferences
- Each has a decay curve and reinforcement on activation
- Persistence via engine memory protocols

**[turing-004] `SelfModel`, `Mood`, `Drive` ontology registration — Proposed; `gap-impl` — v1.0 M1**
- Register at boot via the engine Ontology API (`engine#engine-030`)
- Memory records carry `entity_id` references to the registered self
- Blocked-by: `[engine#engine-030]`

### M2 — Episodic memory + provenance

**[turing-010] 7-tier memory implementation — Proposed; `gap-impl` — v1.0 M2**
- Tiers: OBSERVATION → HYPOTHESIS → OPINION → LESSON → REGRET → AFFIRMATION → WISDOM
- Each tier has weight bounds + decay curve
- Substrate: `[engine#ADR-016]` episodic-store, `[engine#ADR-017]` outcome-store

**[turing-011] Weight floors for REGRET (≥0.6) and WISDOM (≥0.9) — Proposed; `gap-impl` — v1.0 M2**
- Structurally unforgettable: clamp on every operation that would lower the weight
- Tested by `turing-034` memory floor preservation

**[turing-012] Activation graph with self-authored edges — Proposed; `gap-impl` — v1.0 M2**
- The self authors edges between memories and drives
- Edge weights influence retrieval ordering
- Persisted as ontology relationships

**[turing-013] Todo → episode provenance enforcement — Proposed; `gap-impl` — v1.0 M2**
- Every self-authored todo points to an episodic memory of tier LESSON+
- The provenance link is required by the data model (Pydantic non-empty validator)
- Tested by `turing-032` decision provenance

### M3 — Self-talk loop

**[turing-020] Continuous self-talk loop — Accepted (spec exists); `gap-impl` — v1.0 M3**
- Spec: `specs/turing-self-talk-loop.yaml`
- Runs without human input; idle-aware (downshifts during high human load)
- Emits trace per loop turn (per `engine#ADR-037`)

**[turing-021] Awareness loop hz tunable — Proposed — v1.0 M3**
- Knob in Copier template (`engine#engine-011`)
- Default proposed at 1Hz; tunable up to the underlying Reactor (1000Hz upper bound)
- Lower hz reduces compute cost; higher hz increases responsiveness

**[turing-022] Memory consolidation job at idle — Accepted (spec exists); `gap-impl` — v1.0 M3**
- Spec: `specs/turing-memory-consolidator.yaml`
- Runs during idle windows; promotes LESSON → WISDOM on reinforcement count
- Substrate: `[engine#ADR-016]`, `[engine#ADR-017]` — to be recast as `Substrate:` cross-refs (see `turing-091`)

**[turing-023] Dossier generation — Accepted (spec exists); `gap-impl` — v1.0 M3**
- Spec: `specs/turing-dossier.yaml`
- The dossier is the autonoetic UX over episodic memory — "who am I, what do I know, what have I done"
- Substrate: `[engine#ADR-016]` (recast pending in `turing-091`)

### M4 — Self-consistency property tests

**[turing-030] Identity continuity property test — Proposed — v1.0 M4**
- See [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) §1 for the contract
- Hypothesis-driven; runs against any selfmodel snapshot pair within a run

**[turing-031] Narrative consistency property test — Proposed — v1.0 M4**
- See [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) §2

**[turing-032] Decision provenance property test — Proposed — v1.0 M4**
- See [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) §3

**[turing-033] Mood plausibility property test — Proposed — v1.0 M4**
- See [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) §4

**[turing-034] Memory floor preservation property test — Proposed — v1.0 M4**
- See [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) §5

**[turing-035] 30-day staging run with all five tests asserted — Proposed — v1.0 M4**
- The v1.0 acceptance gate; failure is a hard fail
- Depends on `[engine#engine-032]` reliability primitives so the run itself doesn't crash

### M5 — Polish + bootstrap

**[turing-040] Reading-order docs aligned with template — Proposed — v1.0 M5**
- Today: `research/project-turing/DESIGN.md` → `autonoetic-self.md` → `specs/` → `sketches/`
- Realign so the order matches the Copier template's generated layout

**[turing-041] Strip Stronghold-only content — Proposed; `gap-impl` — v1.0 M5**
- `ARCHITECTURE.md` (60KB) — review and excise multi-tenant, K8s, enterprise-governance content
- `BACKLOG.md` — already replaced by this file
- `ROADMAP.md` — already replaced
- `src/` — audit for Stronghold-only modules; either remove or move to stronghold
- Coordinated with `[sh#sh-021]` Stronghold-side absorbs anything missing

**[turing-042] Migrate 31 `ADR-K8S-*` records out of this repo — Accepted; `gap-impl` — v1.0 M5**
- Per `[engine#ADR-030]` §4; destination is stronghold
- Coordinated with `[sh#sh-020]`
- Leaves AgentTuring's `docs/adr/` autonoetic-only

**[turing-043] Bootstrap into `engine/templates/autonoetic/` — Proposed; `gap-impl` — v1.0 M5**
- Round-trip via `copier copy` from a fresh dir
- Diff vs current repo → close the diff over 1–2 PRs
- From there, `copier update` is the canonical path
- Blocked-by: `[engine#engine-011]`

## Documentation hygiene (parallel to v1.0)

**[turing-090] Front-matter on Turing specs — Proposed; `gap-spec` — v1.0 (warn-only window)**
- 22 top-level specs in `specs/`
- ~70 nested epic stories in `docs/specs/`
- Per `[engine#ADR-031]` warn-only 30 days, then hard CI; renumber-on-touch (`S-NNN` → `SPEC-NNN` only when touched)

**[turing-091] Memory specs `Substrate:` recast — Accepted; `gap-impl` — v1.0 M3**
- `turing-dossier.yaml` → `substrate: [maistro-engine#ADR-016]`
- `turing-memory-consolidator.yaml` → `substrate: [maistro-engine#ADR-016, maistro-engine#ADR-017]`
- `turing-notebook-live-vault.yaml` → `substrate: [maistro-engine#ADR-011]`
- `turing-obsidian-store.yaml` → `substrate: [maistro-engine#ADR-014]`
- `epic-12-memory-v2` (stub) → promote to engine ADR if it changes architecture, else close as duplicate
- See `[engine#engine-021]`

**[turing-092] Project Turing research consolidation — Proposed — v1.0**
- Today: research lives in `research/project-turing/`
- Decide: stays as research-track-then-promote, or becomes the canonical AgentTuring source
- Likely the latter post-v1.0; for now, both paths coexist

## v1.1 — the autonoetic stack hardens

**[turing-050] Lineage queries — Proposed — v1.1**
- The Conduit can answer "what did you used to think about X?"
- Snapshots of self-model + drives indexed temporally

**[turing-051] Dream loop — Proposed — v1.1**
- Offline replay + consolidation
- May port `Project_mAIstro#S-025 dream-loop` if that spec actually fits autonoetic (per ADR-030 confirmation needed)

**[turing-052] Phantom execution — Proposed — v1.1**
- The self can simulate a route without committing
- "What would I do?" as a first-class operation

**[turing-053] Adversarial hardening of the self-model — Proposed — v1.1**
- Probe the self-model for inconsistency or drift attacks
- Substrate-agnostic; uses `[engine#engine-038]` chaos primitives if shipped

## v1.2 — RASO inner loop formalised

**[turing-060] `epic-13-hyperagents-meta-level` formalised — Proposed — v1.2**
- Today the spec is open-ended; v1.2 makes it Turing-specific concrete

**[turing-061] RASO inner cycle wired to self-talk — Proposed — v1.2**
- Auditor → Mason → extract → store → track
- Feeds back into the self-talk loop, not into production routing

**[turing-062] Tournament evolution scaffolding (internal-only) — Proposed — v1.2**
- Today scaffolded; v1.2 wires to internal-only routing for self-improvement
- Production routing in stronghold is a separate v2.0 item there, not in Turing

## v1.3 — RASO meta-agent

**[turing-070] Meta-agent that modifies activation graph structure — Proposed — v1.3**
- The self-modifying graph is the v1.3 thesis test
- Modifications must pass the v1.0 property tests; failures are rejected

**[turing-071] Parameter-sensitivity learner — Proposed — v1.3**
- Which knobs to turn by inches, which by leaps

**[turing-072] Self-modification gate — Proposed — v1.3**
- The v1.0 property test suite re-runs after every meta-agent edit
- A failure rejects the edit; the meta-agent learns from rejection

## v2.0 — cross-self portability

**[turing-080] Self-model export / import — Proposed — v2.0**
- Export the self-model as a serialisable artifact
- Import into a fresh Conduit; the imported self answers consistency tests as the same self
- This is the strongest test of autonoesis: identity survives the substrate

**[turing-081] Long-horizon recall with confidence calibration — Proposed — v2.0**
- "Do you remember the day in M2 when X?" returns a confidence level alongside the answer
- Confidence is calibrated against retrieval certainty + tier weight

**[turing-082] Synthesised mood + drives from imported episodic record — Proposed — v2.0**
- If a self is imported with no live mood, it can be synthesised from the episodic stream
- The synthesis must be plausible: tested against `turing-033`-equivalent

**[turing-083] Confidence-calibrated routing — Proposed — v2.0**
- Classifier uncertainty → model tier
- Substrate piece if it generalises (`[engine#engine-NNN]` would be opened)

## Discovered gaps (not yet milestoned)

**[turing-100] HEXACO drift bound calibration — Proposed — v1.0 M1**
- The 0.05 L₂ weekly bound is a guess. First weekly re-tests calibrate it.
- If real drift exceeds the bound under no-stress, the bound is wrong.

**[turing-101] Narrative recall idiom decision — Proposed — v1.0 M4**
- LLMs reconstruct, they don't replay
- The narrative-consistency test asserts agreement on actors/outcome/attribution; phrasing is not gated
- If too lax in M4 staging, tighten to assert key claims structurally

**[turing-102] Sleep / off-hours behavior — Proposed — v1.x**
- Does Turing sleep? If so, what does that mean for awareness loop hz, mood, dream-loop?
- Decision pending a v1.0 staging observation

## Items deferred / abandoned

**[turing-200] Production deployment story — Abandoned**
- AgentTuring is an experimental product. Production-readiness is explicitly out of scope per `[engine#ADR-030]`. Multi-tenant production-grade deployment is `stronghold`'s job; if findings here ever land downstream, they get redesigned for multi-tenancy first.

**[turing-201] Multi-tenant Turing — Abandoned**
- Structurally incompatible with the autonoetic posture (one global self).

## Maintenance

- New items get appended; status changes happen in-place.
- IDs are stable. Items never get renumbered.
- When an item is shipped, mark `Implemented` and link the PR.
- When an item is no longer relevant, mark `Abandoned` with a one-line reason. Don't delete.
- Once registry CI lands (`[engine#engine-001]`), this BACKLOG is regenerated from front-matter; hand-edits during the warn window are fine.
