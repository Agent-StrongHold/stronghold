# Backlog (Four-Repo Canonical)

**Identical copies live in every repo of the four-repo system.** Companion to [`ROADMAP.md`](ROADMAP.md). Items are tagged by owning repo:

- `engine-NNN` — `maistro-engine`
- `maistro-NNN` — `Project_mAIstro`
- `turing-NNN` — `AgentTuring`
- `sh-NNN` — `stronghold`

Cross-repo references use `[repo#item-id]` notation.

Maintained per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md). Status follows [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md) lifecycle. Gap markers per [`docs/INVENTORY-ADRS-SPECS.md`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/INVENTORY-ADRS-SPECS.md). External-library adoption per [`engine#ADR-039`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-039-external-library-adoption-policy.md).

## Status legend

| Marker | Meaning |
|---|---|
| Proposed | Open for discussion; not yet binding |
| Accepted | Decision binding; implementation may follow |
| Implemented | Decision shipped; production code matches |
| Superseded | Replaced by a successor |
| Blocked | A `blocked-by:` dependency is unmet |
| Abandoned | Decision deliberately not taken (kept for traceability) |

## Gap legend

| Marker | Meaning |
|---|---|
| `gap-spec` | No spec or ADR captures this decision yet |
| `gap-test` | Spec/ADR exists; no test (or test stub) covers it |
| `gap-impl` | Spec/ADR + test exist; production code does not match |

---

## `maistro-engine` items

### Foundation (M1)

**[engine-001] Registry CI tooling — Accepted; `gap-impl` — v1.0 M1**

**[engine-002] INVENTORY auto-regenerated — Proposed — v1.0 M1**

**[engine-003] Front-matter on existing engine ADRs — Accepted; gradual — v1.0 M1**

**[engine-004] CONTRIBUTING.md and convention docs — Proposed — v1.0 M1** — includes ADR-039

### Templates (M2)

**[engine-010..012] Three Copier templates — Accepted; `gap-impl` — v1.0 M2**

**[engine-013] Two-stream release pipeline — Proposed — v1.0 M2**

### Drift closure (M3)

**[engine-020] K8S-* ADR migration AT → stronghold (coordinator) — Accepted; `gap-impl` — v1.0 M3**

**[engine-021] Memory spec dedup (coordinator) — Accepted; `gap-impl` — v1.0 M3**

**[engine-022] Catalog spec dedup (coordinator) — Accepted; `gap-impl` — v1.0 M3**

### Substrate code parity (M4)

**[engine-030] Ontology Semantic facet — Accepted; `gap-impl` — v1.0 M4**

**[engine-031] Observability primitives — Accepted; `gap-impl` — v1.0 M4**

**[engine-032] Reliability primitives — Accepted; `gap-impl` — v1.0 M4**

### Contracts (M5)

**[engine-040] Pydantic boundary contracts — Proposed — v1.0 M5**

**[engine-041] Hypothesis behavioral property tests — Proposed — v1.0 M5** — Promptfoo service-boundary integration possible

**[engine-042] Pact-style cross-service contracts — Proposed — v1.0 M5**

**[engine-043] Mutation-testing CI wiring — Proposed — v1.0 M5**

### v1.1–v2.0 (engine — original)

**[engine-050] Cross-product agent portability proof — Proposed — v1.1**

**[engine-051] Forge iteration loop primitive — Proposed — v1.1**

**[engine-052] Compliance gap audit on accepted ADRs — Proposed — v1.1**

**[engine-060] Memory v2 (if surfaced) — Proposed — v1.2**

**[engine-061] DSPy task signatures — Proposed — v1.2**

**[engine-062] Mid-session model switching — Proposed — v1.2**

**[engine-070] Ontology Kinetic facet — Proposed — v2.0**

**[engine-071] Ontology Dynamic facet — Proposed — v2.0**

**[engine-072] Cross-tenant ontology sharing — Proposed — v2.0**

**[engine-073] Tournament-based agent evolution wired to production routing — Proposed — v2.0**

### Discovered gaps (engine — original)

**[engine-080] Pact tooling choice — Proposed**

**[engine-081] Mutation-testing exclusion list per repo — Proposed**

**[engine-082] Backup / export semantics for memory — Proposed**

**[engine-083] Disaster-recovery / backup-restore primitives — Proposed**

**[engine-084] Chaos-engineering harness — Proposed**

**[engine-085] Trace export to long-term storage — Proposed**

### NEW — from May 2026 catalog review (engine)

**[engine-090] Chat-UI integration contract — Proposed; `gap-spec` — v1.1**
- OpenAI-compatible + **A2UI for rich UI generation + MCP for tools**
- Substrate: `BlakeMatthews-dev/A2UI` (Apache 2.0, v0.8 preview)
- Tested against OWUI, LibreChat, Lobe Chat as render targets
- Defuses Open WebUI 50-user attribution clause for stronghold tenants

**[engine-091] A2UI version-pin substrate confirmation — Proposed — v1.1**

**[engine-092] CLI-Anything skills bundle — Proposed; `gap-impl` — v1.1**
- 35+ HKUDS/CLI-Anything pre-generated harnesses; service-boundary per `engine#ADR-039`

**[engine-093] Self-CLI generation — Proposed — v1.2**

**[engine-094] MCP server registry survey + catalog seed — Proposed — v1.0 M3**

**[engine-095] Default skills bundle — Proposed; `gap-impl` — v1.0 M3**

**[engine-096] Tournament training-data labeling pipeline — Proposed; `gap-spec` — v1.2**
- Pattern reference: Adala

**[engine-097] Hyperagent graph runtime substrate — Proposed; `gap-impl` — v1.2**
- Promote from `[maistro-200]` to engine substrate

**[engine-098] Memory drift detection — Proposed; `gap-spec` — v1.1**
- Pattern reference: `compemperor/engram`

---

## `Project_mAIstro` items

### v1.0 — multi-user with hard isolation + setup wizard

**[maistro-001] Setup wizard — Proposed — v1.0** — `S-139`. v1.0 critical path

**[maistro-002] Per-user memory isolation — Proposed — v1.0**

**[maistro-003] Multi-user auth — Proposed — v1.0** — Possible AuthX integration

**[maistro-004] Native install + Podman + systemd — Proposed — v1.0**

**[maistro-005] Tailscale-native networking — Proposed — v1.0**

**[maistro-006/007] v1.0 property tests — Proposed**

### Documentation hygiene

**[maistro-090..092, 095] Front-matter, Substrate recasts, Copier bootstrap — Proposed/Accepted**

### v1.1–v2.0 (mAIstro — original)

**[maistro-100] Voice + email + Alexa channels — Proposed — v1.1**

**[maistro-101..103] Hardware-signing / trust root / DID-VC — Proposed — v1.1**

**[maistro-200] Hyperagent graph runtime — Proposed — v1.2** — substrate is `[engine-097]`

**[maistro-201] Node-graph designer (low-code) — Proposed — v1.2** — **adopt Flowise via service bridge**

**[maistro-202] Human-as-node HITL primitive — Proposed — v1.2**

**[maistro-300] Cross-self portability for households — Proposed — v2.0**

### NEW — from May 2026 catalog review (mAIstro)

**[maistro-150] Prediction-pool feature for Conductor-to-Conductor play — Proposed — v1.2**
- Wraps `Khamel83/vig` (TypeScript / Cloudflare; service-boundary)
- First user-facing exercise of cross-deployment A2A

**[maistro-151] Cross-deployment A2A test scenario — Proposed — v1.1**

**[maistro-400] Davinci-canvas backend expansion — Proposed; `gap-impl` — v1.1**
- `fal-mcp-server` (FLUX, SD, MusicGen) for generation
- `cli-anything-gimp` for editing; `cli-anything-libreoffice` for book-builder layout
- All service-boundary per `engine#ADR-039`

**[maistro-401] Davinci-canvas frontend completion — Proposed; `gap-impl` — v1.1**

---

## `AgentTuring` items

Full v1.0 detail in [`AgentTuring/ROADMAP-v1.0.md`](https://github.com/BlakeMatthews-dev/AgentTuring/blob/main/ROADMAP-v1.0.md).

### v1.0 — measurable autonoesis

**[turing-001..004] HEXACO + mood + drives + ontology registration — Proposed; `gap-impl` — v1.0 M1**

**[turing-010..013] 7-tier memory + provenance — Proposed; `gap-impl` — v1.0 M2**

**[turing-020..023] Self-talk loop + dossier + memory consolidation — Accepted (specs); `gap-impl` — v1.0 M3**

**[turing-030..034] Five property tests — Proposed — v1.0 M4**

**[turing-035] 30-day staging run (acceptance gate) — Proposed — v1.0 M4**

**[turing-040..043] Polish + bootstrap — Proposed/Accepted; `gap-impl` — v1.0 M5**

### Documentation hygiene (Turing)

**[turing-090..092, 095] Front-matter, Substrate recasts, contract markers — Proposed/Accepted**

### v1.1–v2.0 (Turing)

**[turing-050..053] Lineage / dream / phantom / adversarial hardening — Proposed — v1.1**

**[turing-060..062] RASO inner loop — Proposed — v1.2** — 062 substrate: `[engine-096]`

**[turing-070..072] RASO meta-agent — Proposed — v1.3**

**[turing-080..083] Cross-self portability + long-horizon recall — Proposed — v2.0**

### Discovered gaps (Turing)

**[turing-100] HEXACO drift bound calibration — Proposed — v1.0 M1**

**[turing-101] Narrative recall idiom decision — Proposed — v1.0 M4**

**[turing-102] Sleep / off-hours behavior — Proposed — v1.x**

### Items deferred / abandoned (Turing)

**[turing-200] Production deployment — Abandoned**

**[turing-201] Multi-tenant Turing — Abandoned**

---

## `stronghold` items

Full v1.0 detail in [`stronghold/ROADMAP-v1.0.md`](ROADMAP-v1.0.md).

### v1.0 — compliance-first

**[sh-001..003] Multi-tenant catalog wrapper + namespacing + cross-tenant import — Proposed; `gap-impl` — v1.0 W1**

**[sh-010..012] OPA / Cedar / Sentinel policy adapters — Proposed; `gap-impl` — v1.0 W2**

**[sh-020..021] Receive K8S-* records + absorb stronghold-only content — Accepted/Proposed; `gap-impl` — v1.0 W3**

**[sh-030..032] COMPLIANCE.md OWASP + NIST + EU AI Act — Proposed; `gap-impl` — v1.0 W4** — AT-10 anchored to `[engine#ADR-039]`

**[sh-040] Two-tenant red-team CI — Proposed; `gap-impl` — v1.0 W5**

**[sh-050] On-prem (OKD) + cloud (AKS) parity — Proposed; `gap-impl` — v1.0 W6**

**[sh-060] Append-only audit chain — Proposed; `gap-impl` — v1.0 W7**

**[sh-070] v1.0 acceptance suite green — Proposed — v1.0 W8**

**[sh-080] Bootstrap into multi-tenant Copier template — Proposed; `gap-impl` — v1.0 W8**

### Documentation hygiene (Stronghold)

**[sh-090, 095] Front-matter + contract markers — Proposed**

### v1.1–v2.0 (Stronghold — original)

**[sh-100] Trust-tier auto-promotion gates — Proposed — v1.1**

**[sh-101] Forge iteration loop (stronghold side) — Proposed — v1.1**

**[sh-102] Tournament evolution wired to internal-only routing — Proposed — v1.1** — Substrate: `[engine-096]`

**[sh-200] Forge test→iterate loop — Proposed — v1.2**

**[sh-201] Memory decay function in learnings — Proposed — v1.2**

**[sh-300] Agent marketplace — Proposed — v1.3**

**[sh-301] Multi-region failover — Proposed — v1.3**

**[sh-400] SOC 2 Type II audit — Proposed — v2.0**

**[sh-401] ISO 27001 readiness — Proposed — v2.0**

**[sh-402] Sectoral regulators (HIPAA, FedRAMP) — Proposed — v2.0**

### Discovered gaps (Stronghold)

**[sh-500..503] Policy latency, K8S churn, consent flow design, OWASP evidence — Proposed — v1.0**

### NEW — from May 2026 catalog review (Stronghold)

**[sh-600] CLI-Hub federation — Proposed; `gap-impl` — v1.1**
- Multi-tenant catalog ingests from `clianything.cc` (HKUDS) with tenant-scoped enable/disable + audit

**[sh-601] Forge × CLI-Anything pairing — Proposed; `gap-impl` — v1.2**
- Forge invokes CLI-Anything when a skill request maps to existing software; output skills are source-derived

**[sh-602] A2UI render layer for stronghold tenants — Proposed — v1.0 W4**
- Implements `[engine-090]` chat-UI integration contract for tenants
- Resolves Open WebUI 50-user attribution clause concern

**[sh-603] Default skills bundle for tenants — Proposed; `gap-impl` — v1.0 W1**
- Inherits `[engine-095]` plus tenant-scoping + policy bindings

**[sh-604] Promptfoo as eval-substrate CI tool — Proposed — v1.0 W5**
- Service-boundary tool per `engine#ADR-039`

**[sh-605] Open Interpreter as sandboxed code execution — Proposed — v1.0 W2**
- Service-boundary candidate via MCP for stronghold sandbox isolation

---

## Maintenance

- This file is **identical across all four repos**. Any edit lands in all four.
- IDs are stable. Items never get renumbered.
- When an item is shipped, mark `Implemented` and link the PR.
- When an item is no longer relevant, mark `Abandoned` with a one-line reason. Don't delete.
- Once `engine-001` (registry CI) ships, this BACKLOG is regenerated from front-matter.
- External-library decisions follow `engine#ADR-039`.
