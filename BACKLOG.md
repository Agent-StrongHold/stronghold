# Backlog (Four-Repo Canonical)

**Identical copies live in every repo of the four-repo system.** Companion to [`ROADMAP.md`](ROADMAP.md). Items are tagged by owning repo:

- `engine-NNN` — `maistro-engine`
- `maistro-NNN` — `Project_mAIstro`
- `turing-NNN` — `AgentTuring`
- `sh-NNN` — `stronghold`

Maintained per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md). Status follows [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md). Gap markers per [`engine/docs/INVENTORY-ADRS-SPECS.md`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/INVENTORY-ADRS-SPECS.md).

## Status legend

| Marker | Meaning |
|---|---|
| Proposed | Open for discussion |
| Accepted | Decision binding |
| Implemented | Decision shipped |
| Superseded | Replaced by a successor |
| Blocked | A `blocked-by:` dependency is unmet |
| Abandoned | Decision deliberately not taken |

## Gap legend

| Marker | Meaning |
|---|---|
| `gap-spec` | No spec or ADR captures this decision yet |
| `gap-test` | Spec/ADR exists; no test covers it |
| `gap-impl` | Spec/ADR + test exist; production code does not match |

---

## `maistro-engine` items

### Foundation (M1)

**[engine-001] Registry CI tooling — Accepted; `gap-impl` — v1.0 M1**
- Front-matter validator + cross-repo link checker + registry generator + GitHub Action
- Warn-only → hard fail at day 30

**[engine-002] INVENTORY auto-regenerated — Proposed — v1.0 M1**

**[engine-003] Front-matter on existing engine ADRs — Accepted; gradual — v1.0 M1**

**[engine-004] CONTRIBUTING.md and convention docs — Proposed — v1.0 M1**

### Templates (M2)

**[engine-010] Copier template `single-tenant-multi-user` — Accepted; `gap-impl` — v1.0 M2**

**[engine-011] Copier template `autonoetic` — Accepted; `gap-impl` — v1.0 M2**

**[engine-012] Copier template `multi-tenant` — Accepted; `gap-impl` — v1.0 M2**

**[engine-013] Two-stream release pipeline — Proposed — v1.0 M2**

### Drift closure (M3)

**[engine-020] K8S-* ADR migration AT → stronghold (coordinator) — Accepted; `gap-impl` — v1.0 M3**

**[engine-021] Memory spec dedup (coordinator) — Accepted; `gap-impl` — v1.0 M3**

**[engine-022] Catalog spec dedup (coordinator) — Accepted; `gap-impl` — v1.0 M3**

### Substrate code parity (M4)

**[engine-030] Ontology Semantic facet — Accepted; `gap-impl` — v1.0 M4**
- Per `[engine#ADR-036]`. v1.0 ships Semantic only

**[engine-031] Observability primitives — Accepted; `gap-impl` — v1.0 M4**
- Per `[engine#ADR-037]`. 12 spans, 6 metrics, 5 event topics

**[engine-032] Reliability primitives — Accepted; `gap-impl` — v1.0 M4**
- Per `[engine#ADR-038]`. retry/circuit-breaker/fallback/SLO/healthchecks

### Contracts (M5)

**[engine-040] Pydantic boundary contracts — Proposed — v1.0 M5**
- ≥95% mutation kill rate at v1.0

**[engine-041] Hypothesis behavioral property tests — Proposed — v1.0 M5**
- ≥80% kill rate

**[engine-042] Pact-style cross-service contracts — Proposed — v1.0 M5**
- ≥75% kill rate

**[engine-043] Mutation-testing CI wiring — Proposed — v1.0 M5**

### v1.1–v2.0 (engine)

**[engine-050] Cross-product agent portability proof — Proposed — v1.1**

**[engine-051] Forge iteration loop primitive — Proposed — v1.1**

**[engine-052] Compliance gap audit on accepted ADRs — Proposed — v1.1**

**[engine-060] Memory v2 (if surfaced) — Proposed — v1.2**

**[engine-061] DSPy-style task signatures evaluation — Proposed — v1.2**

**[engine-062] Mid-session model switching primitive — Proposed — v1.2**

**[engine-070] Ontology Kinetic facet — Proposed — v2.0**

**[engine-071] Ontology Dynamic facet — Proposed — v2.0**

**[engine-072] Cross-tenant ontology sharing — Proposed — v2.0**

**[engine-073] Tournament-based agent evolution wired to production routing — Proposed — v2.0**

### Discovered gaps (engine)

**[engine-080] Pact tooling choice — Proposed**

**[engine-081] Mutation-testing exclusion list per repo — Proposed**

**[engine-082] Backup / export semantics for memory — Proposed**

**[engine-083] Disaster-recovery / backup-restore primitives — Proposed**

**[engine-084] Chaos-engineering harness — Proposed**

**[engine-085] Trace export to long-term storage — Proposed**

---

## `Project_mAIstro` items

### v1.0 — multi-user with hard isolation + setup wizard

**[maistro-001] Setup wizard — Proposed — v1.0**
- `S-139`. v1.0 critical path. Acceptance: < 30 min for new household

**[maistro-002] Per-user memory isolation — Proposed — v1.0**
- Property test: cross-user retrieval is structurally impossible

**[maistro-003] Multi-user auth (Keycloak / JWT) — Proposed — v1.0**
- Specs: `S-018`, `S-019`, `S-024`

**[maistro-004] Native install + Podman + systemd — Proposed — v1.0**
- Specs: `S-147`, `S-148`

**[maistro-005] Tailscale-native networking — Proposed — v1.0**
- Spec: `S-153`

**[maistro-006] Setup-wizard property test — Proposed — v1.0**

**[maistro-007] Per-user isolation property test — Proposed — v1.0**

### Documentation hygiene

**[maistro-090] Front-matter on mAIstro specs — Proposed; `gap-spec` — v1.0 (warn-only)**
- 91 specs; `S-NNN` → `SPEC-NNN` on touch

**[maistro-091] Memory specs `Substrate:` recast — Proposed; `gap-impl` — v1.0 M3**
- `S-008` → `[engine#ADR-018]` · `S-009` → `[engine#ADR-016]` · `S-032` → `[engine#ADR-016]` · `S-033` → `[engine#ADR-017]`

**[maistro-092] Catalog specs `Substrate:` recast — Proposed; `gap-impl` — v1.0 M3**
- `S-005` → `[engine#ADR-009]` · `S-138` → `[engine#ADR-005/006/009]`

**[maistro-095] Copier bootstrap — Proposed; `gap-impl` — v1.0 M2**

### v1.1–v2.0 (mAIstro)

**[maistro-100] Voice + email + Alexa channels — Proposed — v1.1**

**[maistro-101] Hardware-signing integration — Proposed — v1.1**
- Spec: `S-150`. Substrate: `[engine#ADR-022]`

**[maistro-102] Internal trust root — Proposed — v1.1**
- Spec: `S-155`. Substrate: `[engine#ADR-026]`

**[maistro-103] DID/VC agent identity — Proposed — v1.1**
- Spec: `S-152`. Substrate: `[engine#ADR-024]`

**[maistro-200] Hyperagent graph runtime — Proposed — v1.2**
- Spec: `S-145`

**[maistro-201] Node-graph designer (low-code) — Proposed — v1.2**
- Spec: `S-159`

**[maistro-202] Human-as-node HITL primitive — Proposed — v1.2**
- Spec: `S-158`

**[maistro-300] Cross-self portability for households — Proposed — v2.0**

---

## `AgentTuring` items

Full v1.0 detail in [`AgentTuring/ROADMAP-v1.0.md`](https://github.com/BlakeMatthews-dev/AgentTuring/blob/main/ROADMAP-v1.0.md).

### v1.0 — measurable autonoesis

**[turing-001] HEXACO-24 + weekly retest — Proposed; `gap-impl` — v1.0 M1**
- Drift bound ≤ 0.05 L₂ weekly

**[turing-002] Mood vector with decay + bounded delta — Proposed; `gap-impl` — v1.0 M1**

**[turing-003] Drive store with reinforcement and decay — Proposed; `gap-impl` — v1.0 M1**

**[turing-004] SelfModel/Mood/Drive ontology registration — Proposed; `gap-impl` — v1.0 M1**
- Blocked-by: `[engine-030]`

**[turing-010] 7-tier memory implementation — Proposed; `gap-impl` — v1.0 M2**
- Substrate: `[engine#ADR-016/017]`

**[turing-011] Weight floors REGRET (≥0.6) WISDOM (≥0.9) — Proposed; `gap-impl` — v1.0 M2**

**[turing-012] Activation graph with self-authored edges — Proposed; `gap-impl` — v1.0 M2**

**[turing-013] Todo → episode provenance enforcement — Proposed; `gap-impl` — v1.0 M2**

**[turing-020] Continuous self-talk loop — Accepted (spec); `gap-impl` — v1.0 M3**

**[turing-021] Awareness loop hz tunable — Proposed — v1.0 M3**

**[turing-022] Memory consolidation at idle — Accepted (spec); `gap-impl` — v1.0 M3**

**[turing-023] Dossier generation — Accepted (spec); `gap-impl` — v1.0 M3**

**[turing-030..034] Five property tests — Proposed — v1.0 M4**
- Identity continuity, narrative consistency, decision provenance, mood plausibility, memory floor preservation

**[turing-035] 30-day staging run (acceptance gate) — Proposed — v1.0 M4**
- Depends on `[engine-032]`

**[turing-040] Reading-order docs aligned with template — Proposed — v1.0 M5**

**[turing-041] Strip Stronghold-only content — Proposed; `gap-impl` — v1.0 M5**
- Coordinated with `[sh-021]`

**[turing-042] Migrate K8S-* records out — Accepted; `gap-impl` — v1.0 M5**

**[turing-043] Bootstrap into autonoetic Copier template — Proposed; `gap-impl` — v1.0 M5**

### Documentation hygiene (Turing)

**[turing-090] Front-matter on Turing specs — Proposed; `gap-spec` — v1.0 (warn-only)**

**[turing-091] Memory specs `Substrate:` recast — Accepted; `gap-impl` — v1.0 M3**

**[turing-092] Project Turing research consolidation — Proposed — v1.0**

**[turing-095] Adopt contract markers — Proposed — v1.0 M5**

### v1.1–v2.0 (Turing)

**[turing-050] Lineage queries — Proposed — v1.1**

**[turing-051] Dream loop — Proposed — v1.1**

**[turing-052] Phantom execution — Proposed — v1.1**

**[turing-053] Adversarial hardening of self-model — Proposed — v1.1**

**[turing-060] `epic-13-hyperagents-meta-level` formalised — Proposed — v1.2**

**[turing-061] RASO inner cycle wired to self-talk — Proposed — v1.2**

**[turing-062] Tournament evolution scaffolding (internal-only) — Proposed — v1.2**

**[turing-070] Meta-agent that modifies activation graph — Proposed — v1.3**

**[turing-071] Parameter-sensitivity learner — Proposed — v1.3**

**[turing-072] Self-modification gate — Proposed — v1.3**

**[turing-080] Self-model export / import — Proposed — v2.0**

**[turing-081] Long-horizon recall with confidence calibration — Proposed — v2.0**

**[turing-082] Synthesised mood + drives from imported episodic record — Proposed — v2.0**

**[turing-083] Confidence-calibrated routing — Proposed — v2.0**

### Discovered gaps (Turing)

**[turing-100] HEXACO drift bound calibration — Proposed — v1.0 M1**

**[turing-101] Narrative recall idiom decision — Proposed — v1.0 M4**

**[turing-102] Sleep / off-hours behavior — Proposed — v1.x**

### Items deferred / abandoned (Turing)

**[turing-200] Production deployment — Abandoned**
- Turing is experimental; production is `stronghold`'s job

**[turing-201] Multi-tenant Turing — Abandoned**
- Structurally incompatible with autonoetic posture

---

## `stronghold` items

Full v1.0 detail in [`stronghold/ROADMAP-v1.0.md`](ROADMAP-v1.0.md).

### v1.0 — compliance-first

**[sh-001] Multi-tenant catalog wrapper — Proposed; `gap-impl` — v1.0 W1**
- Wraps engine simple form per `[engine#ADR-035]`

**[sh-002] Tenant-scoped namespacing — Proposed — v1.0 W1**

**[sh-003] Cross-tenant catalog import (with consent) — Proposed — v1.0 W1**

**[sh-010] OPA / Rego policy adapter — Proposed; `gap-impl` — v1.0 W2**
- Hot-reload, < 1ms p99 at 1000 RPS

**[sh-011] Cedar policy adapter — Proposed; `gap-impl` — v1.0 W2**

**[sh-012] Sentinel policy bridge — Proposed — v1.0 W2**

**[sh-020] Receive K8S-* records (renumbered, with substrate refs) — Accepted; `gap-impl` — v1.0 W3**

**[sh-021] Absorb stronghold-only content from AgentTuring strip — Proposed — v1.0 W3**

**[sh-030] COMPLIANCE.md OWASP Agentic Top 10 — Proposed; `gap-impl` — v1.0 W4**

**[sh-031] COMPLIANCE.md NIST AI RMF stub — Proposed — v1.0 W4**

**[sh-032] COMPLIANCE.md EU AI Act stub — Proposed — v1.0 W4**

**[sh-040] Two-tenant red-team CI — Proposed; `gap-impl` — v1.0 W5**

**[sh-050] On-prem (OKD) + cloud (AKS) parity — Proposed; `gap-impl` — v1.0 W6**

**[sh-060] Append-only audit chain — Proposed; `gap-impl` — v1.0 W7**

**[sh-070] v1.0 acceptance suite green — Proposed — v1.0 W8**

**[sh-080] Bootstrap into multi-tenant Copier template — Proposed; `gap-impl` — v1.0 W8**
- Blocked-by: `[engine-012]`

### Documentation hygiene (Stronghold)

**[sh-090] Front-matter on Stronghold specs — Proposed; `gap-spec` — v1.0 (warn-only)**

**[sh-095] Adopt contract markers — Proposed — v1.0 M5**

### v1.1–v2.0 (Stronghold)

**[sh-100] Trust-tier auto-promotion gates — Proposed — v1.1**

**[sh-101] Forge iteration loop (stronghold side) — Proposed — v1.1**

**[sh-102] Tournament evolution wired to internal-only routing — Proposed — v1.1**

**[sh-200] Forge test→iterate loop — Proposed — v1.2**

**[sh-201] Memory decay function in learnings — Proposed — v1.2**

**[sh-300] Agent marketplace — Proposed — v1.3**

**[sh-301] Multi-region failover — Proposed — v1.3**

**[sh-400] SOC 2 Type II audit — Proposed — v2.0**

**[sh-401] ISO 27001 readiness — Proposed — v2.0**

**[sh-402] Sectoral regulators (HIPAA, FedRAMP) — Proposed — v2.0**

### Discovered gaps (Stronghold)

**[sh-500] Policy evaluation latency under load — Proposed — v1.0 W2**

**[sh-501] K8S-* migration churn — Proposed — v1.0 W3**

**[sh-502] Cross-tenant catalog consent flow design — Proposed — v1.0 W1**

**[sh-503] OWASP Agentic Top 10 evidence completeness — Proposed — v1.0 W4**

---

## Maintenance

- This file is **identical across all four repos**. Any edit lands in all four.
- IDs are stable. Items never get renumbered.
- When an item is shipped, mark `Implemented` and link the PR.
- When an item is no longer relevant, mark `Abandoned` with a one-line reason. Don't delete.
- Once `engine-001` (registry CI) ships, this BACKLOG is regenerated from front-matter.
