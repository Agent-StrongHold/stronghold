# Roadmap (Four-Repo Canonical)

**Identical copies live in every repo of the four-repo system:**

- [`BlakeMatthews-dev/maistro-engine`](https://github.com/BlakeMatthews-dev/maistro-engine) (substrate)
- [`BlakeMatthews-dev/Project_mAIstro`](https://github.com/BlakeMatthews-dev/Project_mAIstro) (single-tenant secure multi-user)
- [`BlakeMatthews-dev/AgentTuring`](https://github.com/BlakeMatthews-dev/AgentTuring) (autonoetic experiment)
- [`agent-stronghold/stronghold`](https://github.com/agent-stronghold/stronghold) (multi-tenant enterprise)

The full BACKLOG is the companion: see [`BACKLOG.md`](BACKLOG.md). The four-repo governance that defines this layout is [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md).

See also: [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) for this product's v1.0 acceptance detail.

## Item ID convention

| Prefix | Repo | Concern |
|---|---|---|
| `engine-NNN` | `maistro-engine` | Substrate library, canonical ADRs, Copier templates, registry CI |
| `maistro-NNN` | `Project_mAIstro` | Single-tenant multi-user product (self-hosting) |
| `turing-NNN` | `AgentTuring` | Autonoetic experimental product (continuity of self) |
| `sh-NNN` | `stronghold` | Multi-tenant enterprise product (compliance + isolation) |

Cross-repo references use `[repo#item-id]` notation.

## The system at a glance

| Repo | Role | Dominant constraint |
|---|---|---|
| `maistro-engine` | Substrate library + canonical ADRs + Copier templates + registry CI | n/a (substrate) |
| `Project_mAIstro` | Single-tenant secure multi-user product | **Ease of self-hosting** |
| `AgentTuring` | Autonoetic experimental agent | **Continuity of self** |
| `stronghold` | Multi-tenant enterprise product | **Multi-tenant isolation** |

## Horizons

- **v1.0** — 3 months. Per-product MVPs ship; substrate code parity reached.
- **v1.1–1.3** — 3–12 months. Hardening and inventory drainage.
- **v2.0** — 12 months. Inventory-clear.

---

## v1.0 (3 months) — organised by cross-repo phase

### Phase A — Foundation enforcement (weeks 1–4)

| Item | Owner | Status |
|---|---|---|
| `[engine-001]` Registry CI tooling | engine | Accepted; `gap-impl` |
| `[engine-002]` INVENTORY auto-regenerated | engine | Proposed |
| `[engine-003]` Front-matter on existing engine ADRs | engine | Accepted; gradual |
| `[engine-004]` CONTRIBUTING.md and convention docs | engine | Proposed |
| `[turing-090]` Front-matter on Turing specs | turing | Proposed; warn-only |
| `[sh-090]` Front-matter on Stronghold specs | sh | Proposed; warn-only |
| `[maistro-090]` Front-matter on mAIstro specs | maistro | Proposed; warn-only |

### Phase B — Templates bootstrapped (weeks 2–6)

| Item | Owner | Status |
|---|---|---|
| `[engine-010]` Copier template `single-tenant-multi-user` | engine | Accepted; `gap-impl` |
| `[engine-011]` Copier template `autonoetic` | engine | Accepted; `gap-impl` |
| `[engine-012]` Copier template `multi-tenant` | engine | Accepted; `gap-impl` |
| `[engine-013]` Two-stream release pipeline | engine | Proposed |
| `[maistro-095]` / `[turing-043]` / `[sh-095]` Bootstrap | per repo | Proposed; `gap-impl` |

### Phase C — Drift closure (weeks 3–7)

| Item | Owner | Status |
|---|---|---|
| `[engine-020]` K8S-* ADR migration AT → stronghold | engine (coord) | Accepted; `gap-impl` |
| `[turing-042]` Migrate K8S-* records out of AgentTuring | turing | Accepted; `gap-impl` |
| `[sh-020]` Receive K8S-* records (renumbered, with substrate refs) | sh | Accepted; `gap-impl` |
| `[engine-021]` Memory spec dedup | engine (coord) | Accepted; `gap-impl` |
| `[turing-091]` Memory specs `Substrate:` recast | turing | Accepted; `gap-impl` |
| `[maistro-091]` Memory specs `Substrate:` recast | maistro | Proposed; `gap-impl` |
| `[engine-022]` Catalog spec dedup | engine (coord) | Accepted; `gap-impl` |
| `[maistro-092]` Catalog specs `Substrate:` recast | maistro | Proposed; `gap-impl` |

### Phase D — Substrate code parity (weeks 4–9)

| Item | Owner | Status |
|---|---|---|
| `[engine-030]` Ontology Semantic facet | engine | Accepted; `gap-impl` |
| `[engine-031]` Observability primitives | engine | Accepted; `gap-impl` |
| `[engine-032]` Reliability primitives | engine | Accepted; `gap-impl` |

### Phase E — Per-product v1.0 (weeks 1–12, parallel)

#### Project_mAIstro v1.0 — multi-user with hard isolation + setup wizard

| Item | Status |
|---|---|
| `[maistro-001]` Setup wizard | Proposed |
| `[maistro-002]` Per-user memory isolation | Proposed |
| `[maistro-003]` Multi-user auth | Proposed |
| `[maistro-004]` Native install + Podman + systemd | Proposed |
| `[maistro-005]` Tailscale-native networking | Proposed |
| `[maistro-006]` Setup-wizard property test | Proposed |
| `[maistro-007]` Per-user isolation property test | Proposed |

#### AgentTuring v1.0 — measurable autonoesis

| Item | Status |
|---|---|
| `[turing-001]` HEXACO-24 + weekly retest | Proposed |
| `[turing-002]` Mood vector with decay + bounded delta | Proposed |
| `[turing-003]` Drive store with reinforcement and decay | Proposed |
| `[turing-004]` SelfModel/Mood/Drive ontology registration | Proposed |
| `[turing-010]` 7-tier memory implementation | Proposed |
| `[turing-011]` Weight floors REGRET (≥0.6) WISDOM (≥0.9) | Proposed |
| `[turing-012]` Activation graph with self-authored edges | Proposed |
| `[turing-013]` Todo → episode provenance | Proposed |
| `[turing-020]` Continuous self-talk loop | Accepted; `gap-impl` |
| `[turing-021]` Awareness loop hz tunable | Proposed |
| `[turing-022]` Memory consolidation at idle | Accepted; `gap-impl` |
| `[turing-023]` Dossier generation | Accepted; `gap-impl` |
| `[turing-030..034]` Five property tests | Proposed |
| `[turing-035]` 30-day staging run (acceptance gate) | Proposed |

#### Stronghold v1.0 — compliance-first

| Item | Status |
|---|---|
| `[sh-001]` Multi-tenant catalog wrapper | Proposed; `gap-impl` |
| `[sh-002]` Tenant-scoped namespacing | Proposed |
| `[sh-003]` Cross-tenant catalog import (with consent) | Proposed |
| `[sh-010]` OPA / Rego policy adapter | Proposed; `gap-impl` |
| `[sh-011]` Cedar policy adapter | Proposed; `gap-impl` |
| `[sh-012]` Sentinel policy bridge | Proposed |
| `[sh-020]` K8S-* ADRs migrated in | Accepted; `gap-impl` |
| `[sh-030]` COMPLIANCE.md OWASP Agentic Top 10 | Proposed; `gap-impl` |
| `[sh-031]` COMPLIANCE.md NIST AI RMF stub | Proposed |
| `[sh-032]` COMPLIANCE.md EU AI Act stub | Proposed |
| `[sh-040]` Two-tenant red-team CI | Proposed; `gap-impl` |
| `[sh-050]` On-prem (OKD) + cloud (AKS) parity | Proposed; `gap-impl` |
| `[sh-060]` Append-only audit chain | Proposed; `gap-impl` |

### Phase F — Contracts as the bar (weeks 6–12)

| Item | Owner | Status |
|---|---|---|
| `[engine-040]` Pydantic boundary contracts (≥95% mutation kill rate) | engine | Proposed |
| `[engine-041]` Hypothesis behavioral property tests (≥80%) | engine | Proposed |
| `[engine-042]` Pact-style cross-service contracts (≥75%) | engine | Proposed |
| `[engine-043]` Mutation-testing CI wiring | engine | Proposed |
| `[turing-095]` / `[sh-095]` / `[maistro-095]` Adopt contract markers | per repo | Proposed |

---

## v1.1 (3–6 months) — hardening

| Item | Owner | Status |
|---|---|---|
| `[engine-050]` Cross-product agent portability proof | engine | Proposed |
| `[engine-051]` Forge iteration loop primitive | engine | Proposed |
| `[engine-052]` Compliance gap audit on accepted ADRs | engine | Proposed |
| `[turing-050]` Lineage queries | turing | Proposed |
| `[turing-051]` Dream loop | turing | Proposed |
| `[turing-052]` Phantom execution | turing | Proposed |
| `[turing-053]` Adversarial hardening of self-model | turing | Proposed |
| `[sh-100]` Trust-tier auto-promotion gates | sh | Proposed |
| `[sh-101]` Forge iteration loop — stronghold side | sh | Proposed |
| `[sh-102]` Tournament evolution wired to internal-only routing | sh | Proposed |
| `[maistro-100]` Voice + email + Alexa channels | maistro | Proposed |
| `[maistro-101]` Hardware-signing integration | maistro | Proposed |

## v1.2 (6–9 months) — RASO inner loop + memory v2 if surfaced

| Item | Owner |
|---|---|
| `[engine-060]` Memory v2 (if surfaced) | engine |
| `[engine-061]` DSPy task signatures evaluation | engine |
| `[engine-062]` Mid-session model switching primitive | engine |
| `[turing-060]` `epic-13-hyperagents-meta-level` formalised | turing |
| `[turing-061]` RASO inner cycle wired to self-talk | turing |
| `[turing-062]` Tournament evolution scaffolding (internal-only) | turing |
| `[sh-200]` Forge test→iterate loop | sh |
| `[sh-201]` Memory decay function in learnings | sh |

## v1.3 (9–12 months) — RASO meta-agent + agent marketplace

| Item | Owner |
|---|---|
| `[turing-070]` Meta-agent that modifies activation graph | turing |
| `[turing-071]` Parameter-sensitivity learner | turing |
| `[turing-072]` Self-modification gate | turing |
| `[sh-300]` Agent marketplace | sh |
| `[sh-301]` Multi-region failover | sh |

## v2.0 (12+ months) — inventory-clear

| Item | Owner |
|---|---|
| `[engine-070]` Ontology Kinetic facet | engine |
| `[engine-071]` Ontology Dynamic facet | engine |
| `[engine-072]` Cross-tenant ontology sharing | engine |
| `[engine-073]` Tournament-based agent evolution wired to production routing | engine |
| `[turing-080]` Self-model export / import | turing |
| `[turing-081]` Long-horizon recall with confidence calibration | turing |
| `[turing-082]` Synthesised mood + drives from imported episodic record | turing |
| `[turing-083]` Confidence-calibrated routing | turing |
| `[sh-400]` SOC 2 Type II audit | sh |
| `[sh-401]` ISO 27001 readiness | sh |
| `[sh-402]` Sectoral regulators (HIPAA, FedRAMP) | sh |
| `[maistro-300]` Cross-self portability for households | maistro |

---

## Cross-repo dependency graph (v1.0 critical path)

```
engine-001 (Registry CI)
    │
    ├─→ engine-002 (INVENTORY auto-regen)
    ├─→ engine-021 (Memory dedup)
    │       └─→ turing-091 + maistro-091 (Substrate recast)
    ├─→ engine-022 (Catalog dedup)
    │       └─→ maistro-092 (catalog Substrate recast)
    ├─→ turing-090 + sh-090 + maistro-090 (front-matter)
    └─→ (CI flips hard at day 30)

engine-010/011/012 (Copier templates)
    ├─→ maistro-095 (single-tenant template bootstrap)
    ├─→ turing-043 (autonoetic template bootstrap)
    └─→ sh-095 (multi-tenant template bootstrap)

engine-030 (Ontology) → turing-004
engine-031 (Observability) → turing-020 + sh-060
engine-032 (Reliability) → turing-035 + sh-050

engine-020 (K8S-* migration coord)
    ├─→ turing-042 (out of AgentTuring)
    └─→ sh-020 (into stronghold)
```

## Progress dashboard

```
Phase A Foundation enforcement      [~] ████████░░  80%
Phase B Templates bootstrapped      [·] ░░░░░░░░░░   0%
Phase C Drift closure                [~] █████░░░░░  50%
Phase D Substrate code parity        [·] ░░░░░░░░░░   0%
Phase E.maistro mAIstro v1.0         [·] ░░░░░░░░░░   0%
Phase E.turing  Turing v1.0          [~] ██░░░░░░░░  20%
Phase E.sh      Stronghold v1.0      [~] ██████░░░░  60%
Phase F Contracts as the bar         [~] ███░░░░░░░  30%
```

Legend: `[x]` complete | `[~]` in progress | `[·]` not started

## Per-product detail

- mAIstro v1.0 — [`Project_mAIstro/ROADMAP-v1.0.md`](https://github.com/BlakeMatthews-dev/Project_mAIstro/blob/main/ROADMAP-v1.0.md) (proposal pending; `engine/docs/proposals/Project_mAIstro/`)
- Turing v1.0 — [`AgentTuring/ROADMAP-v1.0.md`](https://github.com/BlakeMatthews-dev/AgentTuring/blob/main/ROADMAP-v1.0.md)
- Stronghold v1.0 — [`stronghold/ROADMAP-v1.0.md`](ROADMAP-v1.0.md) (this repo)

## Maintenance

- This file is **identical across all four repos**. Any edit lands in all four.
- Items get appended; status changes happen in-place. IDs are stable; never renumbered.
- Once `engine-001` (registry CI) ships, ROADMAP and BACKLOG are regenerated from front-matter; hand-edits then fail CI.
