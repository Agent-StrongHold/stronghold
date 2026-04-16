# Stronghold

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**Security-first agent governance platform.** Every design decision in Stronghold starts with "how can this be exploited?" and works backward to function. It wraps any LLM in a zero-trust execution harness with defense-in-depth threat detection, intelligent model routing, self-improving memory, and protocol-driven extensibility.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

## Origin

Stronghold is extracted from **Project Maistro** (a.k.a. Conductor), a private homelab AI gateway that proved the core concepts — routing, memory, multi-agent orchestration, and basic security. Maistro was *security and function*. Stronghold is **security-first design, then function** — security is not a feature bolted on top, it is the foundation upon which every architectural decision is made.

The initial commit (March 25, 2026) ported ~520 files and 2,785 tests from Maistro, already shipping the full Warden/Gate/Sentinel security stack, 6-agent roster, scarcity-based model routing, and self-improving memory. Everything since is Stronghold-native development built on the security-first redesign.

## Timeline

| Date | Milestone |
|---|---|
| Pre-2026 | Project Maistro — homelab AI gateway proving routing, memory, multi-agent concepts |
| **Mar 25** | **Stronghold v0.1.0** — initial commit, ~520 files, 2,785 tests. Full security stack (Warden, Gate, Sentinel), 6-agent roster, model routing, memory, skills. Ported from Maistro with security-first redesign. |
| Apr 1 | Frank + Mason builder pipeline, deterministic strategies, issue-driven feedback loops |
| Apr 2 | Builders 2.0 — unified agent architecture, learning strategy with repo recon and self-diagnosis |
| Apr 6–9 | CI hardening, ruff cleanup, lint/type strictness across all modules |
| Apr 12 | 95% test coverage — 550+ tests, 6 bug fixes |
| **Apr 16** | Feature comparison; RASO direction shift influenced by [Hyperagents](https://arxiv.org/abs/2603.19461) paper |

## Quick Start

```bash
docker compose up -d
curl http://localhost:8100/health
```

## Feature Comparison

How Stronghold compares to other agent frameworks and platforms. Stronghold is an opinionated governance platform — not just an orchestration library or a coding agent — so some comparisons are apples-to-oranges by design.

**Legend:** ✅ = Implemented&ensp; 🟡 = Partial / requires integration&ensp; 🗺️ = Roadmapped&ensp; ❌ = No competitor offers this

> Full feature-by-feature breakdown with detailed analysis: **[COMPARISON.md](COMPARISON.md)**

| Feature | Stronghold | Closest Competitor | Gap |
|---|:---:|---|---|
| **Architecture & Deployment** | | | |
| Open source (Apache 2.0) | ✅ | Most frameworks (MIT) | Archestra is AGPL-3.0; Hyperagents CC BY-NC-SA |
| Self-hosted + K8s native | ✅ | MS Agent Framework, Archestra | Both also ship Helm charts; most others are library-only |
| Protocol-driven DI (20 protocols) | ✅ | MS Agent Framework | Only other framework with pluggable protocol interfaces |
| **Multi-Agent Orchestration** | | | |
| Shipped agent roster (6 agents) | ✅ | ❌ | No framework ships production-ready specialist agents |
| 4 reasoning strategies + custom | ✅ | LangGraph, CrewAI | Graph nodes (LangGraph) and process types (CrewAI) are comparable |
| Intent classification (keyword + LLM) | ✅ | LangGraph 🟡 | LangGraph supports conditional routing but no built-in classifier |
| Multi-intent parallel dispatch | ✅ | MS Agent Framework, LangGraph, CrewAI | All support parallel execution; none have built-in intent splitting |
| Tournament-based agent evolution | ✅ | ❌ | Unique to Stronghold |
| Dynamic intent creation | ✅ | ❌ | Unique to Stronghold |
| Proactive behavior (Reactor) | ✅ | OpenClaw 🟡 | OpenClaw has basic cron; no framework has a 1000Hz event-driven reactor |
| GitAgent import/export | ✅ | ❌ | Unique to Stronghold |
| **Security & Governance** | | | |
| Input scanning (Warden) | ✅ | OpenAI Agents SDK, MS Agent Framework, Archestra | All four scan user input; approaches differ (regex+LLM vs guardrails vs dual-LLM) |
| Tool result scanning (Warden) | ✅ | OpenAI Agents SDK, MS Agent Framework, Archestra | Stronghold + these three are the only ones scanning tool results |
| Output scanning (Sentinel) | ✅ | OpenAI Agents SDK, MS Agent Framework, Archestra, Claude Code | Claude Code uses OS-level sandboxing rather than content scanning |
| Trust tiers (☠️→T0) | ✅ | MS Agent Framework | Only other framework with tiered trust; Stronghold has 5 tiers with earned promotion |
| Schema validation & repair | ✅ | OpenAI Agents SDK | OpenAI uses Pydantic validation; Stronghold adds fuzzy repair of hallucinated args |
| PII filtering | ✅ | MS Agent Framework, Archestra | All three scan outbound responses |
| Config-driven RBAC | ✅ | MS Agent Framework, Archestra | MS uses Entra ID; Archestra uses org/team scoping; Stronghold supports both Keycloak + Entra |
| Per-agent tool permissions | ✅ | MS Agent Framework, Archestra, CrewAI | Stronghold enforces via LiteLLM per-key config |
| Rate limiting | ✅ | MS Agent Framework, Archestra | All three enforce at the gateway level |
| Zero-trust architecture | ✅ | MS Agent Framework 🟡, Archestra 🟡 | Stronghold is the only framework designed zero-trust end-to-end |
| **Memory & Learning** | | | |
| 7-tier episodic memory | ✅ | ❌ | Unique to Stronghold — regrets (≥0.6) structurally unforgettable |
| Self-improving learnings (fail→succeed) | ✅ | Hyperagents ✅, Claude Code 🟡 | Hyperagents: research-only metacognitive loop; Claude Code: static auto-memory |
| 5 memory scopes (global→session) | ✅ | MS Agent Framework 🟡 | MS has pluggable memory backends but not 5-level scoped retrieval |
| Memory decay & reinforcement | ✅ | ❌ | Unique to Stronghold |
| Auto-promotion of corrections | ✅ | ❌ | Unique to Stronghold |
| Knowledge/RAG (pgvector) | ✅ | MS Agent Framework | Both have built-in vector retrieval |
| RASO (self-modifying agent graph) | 🗺️ | Hyperagents (research) | Hyperagents is CC BY-NC-SA research code; Stronghold builds natively from existing primitives |
| **Model Routing** | | | |
| Intelligent cost/quality routing | ✅ | Archestra | Archestra uses a dynamic optimizer (up to 96% cost reduction); Stronghold uses scarcity-based scoring |
| Automatic fallback (429/5xx) | ✅ | MS Agent Framework, Archestra, Pi | All four handle provider failures with automatic model fallback |
| Task-type speed bonuses | ✅ | ❌ | Unique to Stronghold — voice gets speed weight, code gets quality weight |
| Token budget enforcement | ✅ | MS Agent Framework, Archestra, Pi | All four enforce per-request token budgets |
| **Tool Ecosystem** | | | |
| MCP support | ✅ | Claude Code, OpenAI Agents SDK, MS Agent Framework, Archestra | Stronghold via LiteLLM gateway; Archestra has 858+ server registry |
| AI tool/agent creation (Forge) | ✅ | ❌ | Unique to Stronghold — agents create tools, validated via security scanner |
| OpenAPI auto-conversion | ✅ | MS Agent Framework | Both auto-convert OpenAPI specs to callable tools |
| Skill marketplace | ✅ | Archestra, MS Agent Framework, OpenClaw | Archestra has largest catalog (858+ servers) |
| **Observability** | | | |
| OTEL tracing | ✅ | MS Agent Framework, OpenAI Agents SDK, LangGraph | All use OTEL; Stronghold routes to Arize Phoenix |
| Prompt management (PostgreSQL) | ✅ | LangGraph 🟡 | LangGraph uses LangSmith (SaaS); Stronghold uses self-hosted PostgreSQL |
| Cost tracking | ✅ | MS Agent Framework, Archestra, Pi | All four track per-request costs |
| **Enterprise & Multi-Tenant** | | | |
| SSO / OIDC | ✅ | MS Agent Framework, LangGraph Platform | Stronghold supports both Keycloak and Entra ID |
| Multi-tenant isolation | 🗺️ | MS Agent Framework, Archestra, LangGraph Platform | All three have production multi-tenancy today |
| Namespace-scoped secrets | 🗺️ | MS Agent Framework, Archestra | Both have per-tenant secret management |
| Agent marketplace | 🗺️ | MS Agent Framework, Archestra | Both have agent/tool registries |

### What Makes Stronghold Different

Most agent frameworks give you **building blocks** (LangGraph, OpenAI Agents SDK) or a **finished product** (Claude Code, OpenClaw). Stronghold is an **opinionated governance platform** — it ships with a complete agent roster, security scanning at every trust boundary, self-improving memory, and intelligent model routing, all behind swappable protocol interfaces.

**Unique to Stronghold:**
- **Defense-in-depth security** — Warden scans both user input *and* tool results before they enter LLM context. Sentinel enforces policy at every boundary crossing. No other framework scans tool results by default.
- **5-tier trust system** — Tools and agents earn trust through automated validation and operator approval (☠️ → T3 → T2 → T1 → T0). Only MS Agent Framework has comparable trust tiers.
- **Self-improving memory** — Learns from tool-call failures (fail→succeed extraction), auto-promotes corrections after N successful uses, bridges to 7-tier episodic memory with structural weight floors. No other platform combines learning extraction with tiered episodic memory and decay.
- **Scarcity-based model routing** — Cost rises smoothly as provider token pools deplete. No cliffs, no manual rebalancing. Only Archestra has comparable intelligent routing (via a dynamic optimizer).
- **Tournament-based agent evolution** — Agents compete head-to-head on live traffic; winners earn routes. No other framework has this.
- **Protocol-driven DI with zero direct external imports** — Business logic depends only on protocols. LiteLLM, Arize, PostgreSQL — all swappable without touching a single line of business logic.

**Roadmap — Reflexive Agentic Self-Optimization (RASO):** Stronghold's builders loop already implements plan → execute → review → learn → iterate with automatic learning extraction and correction promotion. The RASO roadmap wraps a meta-agent around this graph so it can modify its own structure (add/remove/reorder nodes, adjust strategy selection, tune scoring weights), treating the entire workflow as both a pipeline of agents *and* an agent itself. This concept was on Stronghold's roadmap with skeletal tests and code snippets before Meta published their [Hyperagents](https://arxiv.org/abs/2603.19461) paper (March 2026); Hyperagents has since informed the renewed design. Previously called "naive RLHF" internally, but renamed: there's no human feedback in the loop — it's agent feedback from tournament scoring, learning extraction, and automated quality gates. *Direction shifted April 16, 2026 based on influence of Hyperagents paper.* Built entirely from existing Stronghold primitives under Apache 2.0.

## License

Apache 2.0 — see [LICENSE](LICENSE).
