# Stronghold — Compliance Mappings

**Status:** v1.0 critical path (per [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) and [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md)).

This document maps Stronghold's controls to:

- **OWASP Agentic Top 10** (full mapping at v1.0)
- **NIST AI Risk Management Framework** (Govern, Map, Measure, Manage — stub at v1.0; full at v1.5)
- **EU AI Act** (high-risk system requirements, Articles 9–15, 17, 26 — stub at v1.0; full at v1.5)
- **SOC 2 Type II** (Trust Services Criteria — evidence catalog at v1.5; audit at v2.0)

Each mapping line cites the Stronghold module(s) that satisfy the control AND the test path(s) that prove it. Lines without a test path are flagged `gap-test`. Lines without a module path are flagged `gap-impl`. Lines with no plan are flagged `gap-spec`.

## Legend

| Marker | Meaning |
|---|---|
| ✅ | Implemented and tested |
| 🟡 | Implemented; test path missing (`gap-test`) |
| 🟠 | Spec'd; not yet implemented (`gap-impl`) |
| ⚪ | No spec yet (`gap-spec`) |
| — | Not applicable to Stronghold |

---

## OWASP Agentic Top 10

Reference: OWASP Top 10 for AI-Agentic Systems, 2026 baseline.

| ID | Risk | Stronghold control | Test path | Status |
|---|---|---|---|---|
| **AT-01** | Memory poisoning | Warden three-boundary scan + 7-tier episodic with weight floors + auto-promotion gating | `tests/security/test_warden_*.py`; `tests/memory/test_weight_floor.py` | 🟡 (test path placeholder pending audit) |
| **AT-02** | Tool misuse | Per-agent tool permissions via LiteLLM key config + Sentinel output scan + tenant-scoped catalog (per [`engine#ADR-035`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-035-catalog-ownership-split.md)) | `tests/security/test_tool_acl.py` | 🟡 |
| **AT-03** | Privilege compromise | 5-tier earned trust (☠️→T0) + Casbin RBAC + per-tenant SSO (Keycloak / Entra) | `tests/security/test_trust_tier.py`; `tests/security/test_rbac.py` | 🟡 |
| **AT-04** | Resource overload | Quota module + circuit breakers (per [`engine#ADR-038`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-038-reliability-taxonomy.md)) + scarcity-based router pricing | `tests/quota/test_*.py`; `tests/reliability/test_circuit_breaker.py` | 🟡 |
| **AT-05** | Cascading failures | Circuit breakers per-dependency + Fallback[T] type + per-trigger circuit breakers in Reactor + LiteLLM model fallback chain | `tests/reliability/test_fallback_chain.py` | 🟠 (per `engine#ADR-038` impl) |
| **AT-06** | Identity spoofing | Cryptographic agent identity (per [`engine#ADR-022`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-022-hardware-signing.md), [`engine#ADR-023`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-023-agent-crypto-ops.md), [`engine#ADR-024`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-024-agent-identity-did-vc.md)) + B2B service keys + JWT with bounded scope | `tests/security/test_agent_identity.py` | 🟠 |
| **AT-07** | Misaligned objectives | Spec-driven verification (Quartermaster + Archie) + Auditor `SPEC_COVERAGE_GAP` gate + Sentinel output scan vs declared scope | `tests/builders/test_spec_coverage.py` | 🟡 |
| **AT-08** | Repudiation / lack of accountability | Append-only audit chain (per `ROADMAP-v1.0.md` W7) + per-tenant audit retention indefinite + signed events | `tests/audit/test_chain_integrity.py` | 🟠 (W7) |
| **AT-09** | Overreliance / lack of human oversight | Trust tier with manual auto-promotion gates (auto-promotion roadmapped v1.1) + HITL primitive (substrate: `Project_mAIstro#SPEC-158 human-as-node`) + circuit-breaker fallback to Warden agent on uncertainty | `tests/security/test_human_in_loop.py` | ⚪ (HITL primitive `gap-spec` for stronghold; mAIstro SPEC-158 is the substrate) |
| **AT-10** | Supply-chain (MCP / model / dependency) | MCP security scanner (port from Microsoft Agent Governance Toolkit — v1.1) + Bandit + Semgrep + pip-audit + Gitleaks + CodeQL + Dependabot + signed model cards | `tests/security/test_mcp_supply_chain.py` | 🟠 (MCP scanner pending) |

### OWASP gaps to close before v1.0

- **AT-05** Cascading failures: needs `engine#ADR-038` reliability primitives shipped end-to-end, then a property-test asserting cascade is bounded.
- **AT-06** Identity spoofing: needs `engine#ADR-022/023/024` shipped (cryptographic identity); only spec exists today.
- **AT-08** Audit chain: roadmap workstream W7 (weeks 8–12); critical path.
- **AT-09** Human-in-loop: needs a stronghold-side spec referencing `Project_mAIstro#SPEC-158` as substrate; gap is in declaration, not implementation.
- **AT-10** Supply chain: MCP security scanner port roadmapped; everything else (SAST, secrets, deps) is shipped.

## NIST AI Risk Management Framework (AI RMF)

Reference: NIST AI 100-1, NIST AI 100-2 (Generative AI Profile).

### Govern

| Function | Stronghold control | Status |
|---|---|---|
| GOVERN-1 (Policies, processes, structures) | Per-tenant policy-as-code (OPA / Cedar / Sentinel) per `ROADMAP-v1.0.md` W2 | 🟠 |
| GOVERN-2 (Accountability) | Audit chain (W7) + tenant-scoped RBAC + signed events | 🟠 |
| GOVERN-3 (Workforce / culture) | Documentation, ARCHITECTURE.md, ONBOARDING.md, SECURITY.md | 🟡 |
| GOVERN-4 (Engagement / oversight) | HITL primitive (substrate: `Project_mAIstro#SPEC-158`) | ⚪ |
| GOVERN-5 (Lifecycle) | Status lifecycle in front-matter (per [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md)) + ROADMAP-v1.0 / v2.0 | 🟡 |

### Map

| Function | Stronghold control | Status |
|---|---|---|
| MAP-1 (Context) | Per-tenant Warden scan policies + tenant-context-scoped memory | 🟡 |
| MAP-2 (Categorization) | OWASP Agentic Top 10 mapping (this document) | 🟠 |
| MAP-3 (Capabilities) | COMPARISON.md feature-by-feature | ✅ |
| MAP-4 (Risk impact) | This document; risks per OWASP and EU AI Act sections | 🟠 |
| MAP-5 (Risk priority) | v1.0 acceptance gates and `ROADMAP-v1.0.md` workstream prioritisation | ✅ |

### Measure

| Function | Stronghold control | Status |
|---|---|---|
| MEASURE-1 (Identification) | Spec-driven verification (Quartermaster→Archie→Mason→Auditor) | ✅ |
| MEASURE-2 (Tracking) | OTEL traces + Prometheus metrics + audit events (per `engine#ADR-037`) | 🟡 |
| MEASURE-3 (Effectiveness) | Mutation-testing kill rate as quality bar (per `engine#ADR-032`) | ✅ |
| MEASURE-4 (Feedback) | Auditor→Mason loop + tournament-based evolution scaffold | 🟡 |

### Manage

| Function | Stronghold control | Status |
|---|---|---|
| MANAGE-1 (Risk treatment) | Three-boundary scanning + circuit breakers + tenant isolation | 🟡 |
| MANAGE-2 (Allocation) | Per-tenant quota + scarcity-based router pricing | ✅ |
| MANAGE-3 (Pre-deployment) | Tiered coverage gates + assertion-strength gates | 🟡 |
| MANAGE-4 (Documentation / response) | SECURITY.md + audit chain + COMPLIANCE.md (this document) | 🟠 |

## EU AI Act (High-risk systems)

Reference: Regulation (EU) 2024/1689, focus on Articles 9–15 (risk management, data governance, technical documentation, record-keeping, transparency, human oversight, accuracy/robustness/cybersecurity), Article 17 (quality management), and Article 26 (deployer obligations).

| Article | Requirement | Stronghold control | Status |
|---|---|---|---|
| **Art. 9** | Risk-management system | Spec-driven verification + this COMPLIANCE.md + per-tenant policy-as-code | 🟠 |
| **Art. 10** | Data governance | Per-tenant memory isolation + PII filter (Sentinel) + 7-tier episodic with auditable mutations | 🟡 |
| **Art. 11** | Technical documentation | ARCHITECTURE.md (60KB) + ADR ladder + this COMPLIANCE.md | 🟡 |
| **Art. 12** | Record-keeping | Audit chain (W7) + indefinite retention + signed events | 🟠 |
| **Art. 13** | Transparency to users | Sentinel output scan declares filtered content + COMPARISON.md publishes capability claims | 🟡 |
| **Art. 14** | Human oversight | HITL primitive (substrate: `Project_mAIstro#SPEC-158`) + trust-tier manual gates + circuit-breaker fallback to Warden agent | ⚪ |
| **Art. 15** | Accuracy / robustness / cybersecurity | Mutation-testing bar + Hypothesis property tests + Bandit/Semgrep/pip-audit/Gitleaks/CodeQL + per-boundary security scan | ✅ |
| **Art. 17** | Quality management system | CI gate stack (10+ blocking gates) + spec-driven Auditor + assertion-strength CI | 🟡 |
| **Art. 26** | Deployer obligations | Per-tenant audit log access + transparency notices + incident-reporting hook | 🟠 |

## SOC 2 Type II (Trust Services Criteria)

Full evidence catalog deferred to v1.5; audit deferred to v2.0. v1.0 ships the structural prerequisites:

| TSC | Stronghold control | Status |
|---|---|---|
| Security (CC1–CC9) | Three-boundary scan + RBAC + audit chain + crypto identity | 🟡 |
| Availability (A1) | Circuit breakers + SLOs + healthchecks (per `engine#ADR-038`) | 🟠 |
| Processing Integrity (PI1) | Spec-driven verification + boundary contracts + behavioral contracts | ✅ |
| Confidentiality (C1) | Per-tenant memory + namespace-scoped secrets + PII filter | 🟠 |
| Privacy (P1–P8) | PII filter + per-tenant data isolation + audit chain | 🟡 |

## How this document is maintained

- This document is the **source of truth** for stronghold's control claims. ROADMAP-v1.0 workstreams that close `gap-impl` items reference back to here when complete.
- Every line that cites a `tests/...` path must resolve to an existing test (or a `pytest.mark.skip(reason="AT-NN spec'd; pending W*N")`). The registry CI (per [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md), Phase 0g) flags dangling test paths.
- Updates to this document accompany the relevant code/test PR, not as a separate doc-only PR.
- Auditors and prospective customers can ground a request in this document; gap markers signal what's coming, not what's hidden.

## v1.5 and v2.0 follow-up

| Horizon | Addition |
|---|---|
| **v1.5** | Full NIST AI RMF Generative AI Profile mapping; full EU AI Act technical documentation per Annex IV; SOC 2 evidence catalog |
| **v2.0** | SOC 2 Type II audit; ISO 27001 readiness; sectoral regulators (HIPAA, FedRAMP) per customer demand |
