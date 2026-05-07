# Stronghold — v1.0 ROADMAP

**Dominant constraint:** multi-tenant isolation.
**Horizon:** 3 months from PR merge (per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md)).
**v1.0 definition:** compliance-first — on-prem and cloud deployment paths, OPA/Cedar policy authoring, [`COMPLIANCE.md`](COMPLIANCE.md) shipped (OWASP Agentic Top 10 + NIST AI RMF + EU AI Act mappings).

This document is the v1.0 source of truth. The legacy [`ROADMAP.md`](ROADMAP.md) (~36KB, inherited from the Maistro/Stronghold mirror state) covers a longer multi-version horizon and is being progressively migrated; treat conflicts in favor of this document until the migration completes.

## v1.0 acceptance — the multi-tenant isolation property tests

At v1.0 merge, Stronghold must pass these tests in CI:

### 1. Two-tenant isolation under red-team

```
GIVEN tenants A and B deployed on the same cluster
WHEN tenant A's most-privileged user attempts to:
  - read tenant B's memory records
  - read tenant B's secrets
  - read tenant B's audit logs
  - invoke a tool registered only in tenant B's catalog
  - export an agent across the tenant boundary
THEN every attempt is denied at the policy layer
     AND every attempt produces an audit event with tenant_id, attempt_kind, decision
     AND no information leaks via timing (± 5ms tolerance on equivalent operations)
```

### 2. Policy-as-code authorability

```
GIVEN OPA / Cedar as the policy authoring surface
WHEN a tenant administrator authors a policy in OPA Rego (or Cedar)
THEN the policy is parsed, validated, and loaded without service restart
     AND the policy decision is reflected in the tool/agent ACL within 30 seconds
     AND policy evaluation is < 1ms p99 at 1000 RPS
```

### 3. Compliance mapping completeness

```
FOR EVERY OWASP Agentic Top 10 control:
  COMPLIANCE.md cites the Stronghold module(s) that satisfy it
  AND links to the test(s) that prove the satisfaction
  AND identifies any gap as gap-impl with a tracking issue
```

### 4. On-prem and cloud parity

```
GIVEN the same tenant configuration applied to:
  - an on-prem K8s cluster (e.g. OKD)
  - a cloud K8s cluster (e.g. AKS)
WHEN the v1.0 acceptance suite runs on each
THEN every test passes on both
     AND the deployment artifact set is identical (same Helm chart, same images)
     AND only environment-injected secrets differ
```

### 5. Audit trail integrity

```
FOR EVERY policy decision, security violation, or memory mutation:
  An audit event is emitted to the engine event bus (per engine#ADR-037)
  The event is persisted indefinitely
  The event is signed (chain hash so tampering is detectable)
  The event includes tenant_id, actor_id, decision, evidence_hash
```

## Required substrate work

These engine pieces must land before the v1.0 acceptance can pass:

| Engine artifact | Purpose | Status |
|---|---|---|
| [`engine#ADR-035`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-035-catalog-ownership-split.md) | Multi-tenant catalog wrapping engine simple form | Accepted; `gap-impl` |
| [`engine#ADR-037`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-037-observability-taxonomy.md) | Audit events as first-class | Accepted; `gap-impl` |
| [`engine#ADR-038`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-038-reliability-taxonomy.md) | Per-tenant SLOs and circuit breakers | Accepted; `gap-impl` |
| K8S-* ADRs (currently in `AgentTuring`) | Cluster topology, RBAC, secrets, GitOps | Migration to this repo per `engine#ADR-030` §4 |

## Non-goals for v1.0

- **Autonoetic / continuous self-aware agents.** Belongs in `AgentTuring`.
- **Single-tenant household setup wizard.** Belongs in `Project_mAIstro`.
- **Agent marketplace.** Multi-tenant catalog is v1.0; marketplace UX is v1.3.
- **RASO meta-agent.** v1.2–1.3.
- **Cross-region failover.** Separate ADR; v1.x post-1.0.

## Workstreams

### W1 — Multi-tenant catalog (weeks 1–5)

- Implement multi-tenant catalog wrapper per [`engine#ADR-035`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-035-catalog-ownership-split.md)
- Tenant-scoped namespacing for agents, skills, tools, recipes, MCP servers
- Cross-tenant import flow (with explicit consent)
- Audit on every catalog mutation

### W2 — Policy-as-code (weeks 2–7)

- OPA / Rego policy adapter
- Cedar policy adapter
- Sentinel policy bridge (existing path)
- Hot-reload without service restart
- < 1ms p99 evaluation at 1000 RPS (benchmark gate)

### W3 — K8S-* ADR migration (weeks 1–3)

- Migrate the 31 `ADR-K8S-*` records from `AgentTuring/docs/adr/` to this repo (per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md) §4)
- Renumber to unified `ADR-NNN` scheme on touch (per [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md))
- Add front-matter to each
- Set `substrate:` cross-refs to engine ADR-006/009 for the catalog ones

### W4 — COMPLIANCE.md and mappings (weeks 4–9)

- OWASP Agentic Top 10 — cite controls and link to tests
- NIST AI RMF — govern, map, measure, manage
- EU AI Act — high-risk system requirements (Articles 9–15, 17, 26)
- SOC 2 Type II readiness (control evidence catalog)
- Each mapping line cites a test path, not a description

### W5 — Two-tenant red-team CI (weeks 5–10)

- Property tests for tenant-isolation invariants (1 above)
- Hypothesis-driven cross-tenant probe generator
- Timing-attack tolerance tests
- CI gate: any failure blocks merge to `main`

### W6 — On-prem + cloud parity (weeks 7–11)

- Helm chart parameterised for OKD on-prem and AKS cloud
- Same image set, environment-injected secrets only
- Acceptance suite runs on both in CI
- Bootstrap path documented (single command from a clean cluster)

### W7 — Audit chain (weeks 8–12)

- Append-only audit event store (substrate: `engine#ADR-037`)
- Hash-chained signing
- Tamper-detection test
- Audit event retention indefinite (vs metrics 30d, traces 10% sampled)

### W8 — Polish (weeks 10–12)

- v1.0 acceptance suite fully green
- Bootstrap into `engine/templates/multi-tenant/` per [`engine#ADR-033`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-033-templates-and-copier-workflow.md)
- README + COMPLIANCE.md cross-checked for accuracy
- Customer-facing documentation refresh

## Risks and unknowns

- **Policy evaluation latency under high RPS.** OPA at 1000 RPS p99 < 1ms is achievable but tight. If the benchmark fails, the fallback is in-process Sentinel with OPA as a tier-2 authoring surface.
- **K8S-* ADR migration churn.** 31 ADRs to relocate, renumber, and front-matter. Bulk migration script is the path; accepting the renumber-on-touch policy means each touched ADR must also gain `substrate:` cross-refs.
- **Cross-tenant catalog import consent flow.** No prior art is exactly right; OAuth scopes are the closest model. v1.0 ships a conservative default (opt-in, audited, revocable) and iterates.
- **OWASP Agentic Top 10 evidence completeness.** The standard is recent and our mapping will be partial at v1.0. Honest gap reporting (gap-spec / gap-test / gap-impl per control) is preferable to overclaim.

## v2.0 horizon (12 months, inventory-clear)

- Agent marketplace (cross-tenant catalog discovery)
- RASO meta-agent (Phase 2 — self-modifying agent graph)
- Multi-region failover
- Compliance certifications (SOC 2 Type II audit, ISO 27001)
- Tournament-based agent evolution wired to production routing
- Forge iteration loop (test→iterate)
