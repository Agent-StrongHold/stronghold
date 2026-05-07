# AgentTuring

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**An autonoetic agent experiment.** A Conduit that carries a persistent self — personality, mood, passions, skills, todos, prior decisions — and routes from first-person experience rather than stateless classification. One global self, no tenant scoping. The point is to find out what changes when an agent system has a continuous past and a credible future.

## Position in the four-repo system

AgentTuring is one of three products built on the [`maistro-engine`](https://github.com/BlakeMatthews-dev/maistro-engine) substrate (per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md)).

| Repo | Dominant constraint |
|---|---|
| [`maistro-engine`](https://github.com/BlakeMatthews-dev/maistro-engine) | substrate — shared Python runtime + canonical ADRs |
| `Project_mAIstro` | ease of self-hosting (single-tenant secure multi-user) |
| **`AgentTuring`** (this repo) | **continuity of self** (autonoetic experiment) |
| [`stronghold`](https://github.com/agent-stronghold/stronghold) | multi-tenant isolation (enterprise) |

The three products are Copier-templated peers, not a hierarchy. AgentTuring's specs and ADRs cite engine ADRs via `substrate:` cross-refs.

## What AgentTuring is

A near-fork experiment that promotes the Conduit from **noetic** router (classify → route → forget) into an **autonoetic** reasoning layer:

- Remembers its own prior routings as first-person experience
- Projects itself into future routings ("what would I do?")
- Can regret (memories with weight floors that prevent forgetting)
- Can commit (self-authored todos with required provenance)

The self the Conduit carries:

- **HEXACO-24 personality** with weekly re-test
- **Mood vector** that decays and reinforces
- **Passions / hobbies / interests / skills / preferences** with decay curves
- **7-tier episodic memory** — OBSERVATION → HYPOTHESIS → OPINION → LESSON → REGRET → AFFIRMATION → WISDOM
- **Self-authored todos** with required provenance (every task knows why it exists)
- **Activation graph** whose edges the self itself authors

### What AgentTuring is not

- Not a multi-tenant product — there is exactly one self. Multi-tenancy is structurally incompatible with the autonoetic posture and is `stronghold`'s mission.
- Not a self-hosted product for households — that's `Project_mAIstro`'s mission.
- Not a roadmap item for either of those products. If something here works, it gets redesigned for multi-tenancy or self-hosting before any of it lands downstream.
- Not production-ready. This is an experiment.

## v1.0 — measurable autonoesis

v1.0 is defined as **self-consistency-as-tests** (per [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md)). Autonoesis is not a vibe; it is a property test. At v1.0 the Conduit can answer:

- *"What did you do yesterday?"* — with a consistent narrative across runs
- *"What do you believe about yourself?"* — with the same self-model that started the run

…and the property tests assert these answers do not diverge across a 30-day continuous run. See [`ROADMAP-v1.0.md`](ROADMAP-v1.0.md) for the test plan.

## Reading order

1. [`research/project-turing/DESIGN.md`](research/project-turing/DESIGN.md) — thesis, Tulving-taxonomy mapping, what the Conduit becomes when it has a self.
2. [`research/project-turing/autonoetic-self.md`](research/project-turing/autonoetic-self.md) — the content of the self the Conduit carries.
3. [`research/project-turing/specs/`](research/project-turing/specs/) — 30 individually reviewable specs, read in order.
4. [`research/project-turing/sketches/`](research/project-turing/sketches/) — runnable scaffold + tests.

## Branches

- `main` — integration
- `project_Turing` — "main" of the autonoetic pseudo-fork
- `research/project-turing` — active research
- `claude/<topic>-<slug>` — feature work (per [`engine#ADR-001`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-001-branching-strategy.md))

Flow: `feature → research/project-turing → project_Turing → main`.

## Lineage

CoinSwarm (Nov 2025, biological-evolution-inspired trading swarm; origin of 7-tier memory) → 7-tier crystallization (Jan 15, 2026) → Stronghold import (Mar 25, 2026) → Project Turing (Apr 2026, autonoetic Conduit experiment) → **AgentTuring** repo (this product, May 2026).

## Quick start

```bash
docker compose up -d
curl http://localhost:8100/health
```

The stack is deliberately small for an experiment: a single-instance Conduit, pgvector for memory, OpenWebUI for chat, Langfuse for behavioral inspection. Multi-tenancy code paths from the shared engine are disabled.

## Quality bars

Per [`engine#ADR-032`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-032-contracts-as-acceptance-criteria.md):

- **Boundary contracts** (Pydantic) on every public type — ≥95% mutation kill rate
- **Behavioral contracts** (Hoare-style + Hypothesis property tests) for self-consistency invariants — ≥80%
- **Cross-service contracts** (Pact-style) for A2A and MCP edges — ≥75%

Mutation testing runs nightly via `mutmut` (config: [`.mutmut-config.ini`](.mutmut-config.ini)).

## Substrate ADR ladder

This product inherits the engine ADR ladder. Key references:

- [`engine#ADR-019`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-019-canonical-source-split.md) — canonical source split
- [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md) — four-repo governance (this product's role)
- [`engine#ADR-031`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-031-front-matter-and-registry.md) — front-matter and registry conventions
- [`engine#ADR-032`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-032-contracts-as-acceptance-criteria.md) — contracts as acceptance criteria
- [`engine#ADR-033`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-033-templates-and-copier-workflow.md) — Copier-templated products
- [`engine#ADR-034`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-034-memory-canonical-ownership.md) — memory canonical ownership (Turing's memory specs are parameterisations)
- [`engine#ADR-036`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-036-ontology-semantic-object-layer.md) — ontology layer (`SelfModel`, `Mood`, `Drive` register here)
- [`engine#ADR-037`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-037-observability-taxonomy.md) — observability taxonomy
- [`engine#ADR-038`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-038-reliability-taxonomy.md) — reliability taxonomy

## Note on the current state

At the time of this rewrite, this repo and `agent-stronghold/stronghold` share blob-identical READMEs, ARCHITECTURE.md, ROADMAP.md, and source trees — the mirror situation [`engine#ADR-030`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-030-four-repo-governance.md) targets for divergence. The bootstrap into Copier templates ([`engine#ADR-033`](https://github.com/BlakeMatthews-dev/maistro-engine/blob/main/docs/adr/ADR-033-templates-and-copier-workflow.md)) is the path out. Subsequent PRs in this repo will:

1. Strip stronghold-only content (multi-tenant ADRs, K8s topology, enterprise governance) — these belong in `stronghold`.
2. Promote autonoetic content to first-class.
3. Bring the source tree into a Copier-generated shape derived from `engine/templates/autonoetic/`.

## License

Apache 2.0 — see [LICENSE](LICENSE).
