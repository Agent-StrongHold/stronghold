# Stronghold

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Secure Agent Governance Platform. Wraps any LLM in a secure execution harness with intelligent routing, self-improving memory, and zero-trust security.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system design.

## Quick Start

```bash
docker compose up -d
curl http://localhost:8100/health
```

## Feature Comparison

How Stronghold compares to other agent frameworks and platforms. Stronghold is an opinionated governance platform — not just an orchestration library or a coding agent — so some comparisons are apples-to-oranges by design.

**Legend:** ✅ = Full support&ensp; 🟡 = Partial / requires integration&ensp; 🗺️ = Roadmapped&ensp; ❌ = Not available

### Architecture & Deployment

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Open source | ✅ Apache 2.0 | Source-avail. | ✅ MIT | ✅ MIT | ✅ AGPL-3.0 | ✅ MIT | ✅ MIT | ✅ MIT | CC BY-NC-SA | ✅ MIT | ✅ MIT |
| Self-hosted | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Kubernetes native | ✅ | ❌ | ❌ | ✅ | ✅ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Helm charts | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Docker Compose | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Protocol-driven DI | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Language | Python | TS/Rust | Python/TS | .NET/Python | Go | Python/TS | Python | TS | Python | Python | TS |

### Multi-Agent Orchestration

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-agent support | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 🟡 | ❌ |
| Shipped agent roster | ✅ 6 agents | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Reasoning strategies | ✅ 4 generic + custom | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| A2A communication | ✅ | ✅ | ✅ Handoffs | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| Intent classification | ✅ Keyword + LLM | ❌ | ❌ | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ |
| Multi-intent parallel dispatch | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tournament evolution | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Dynamic intent creation | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Proactive behavior (Reactor) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | 🟡 Cron | ❌ | ❌ | ❌ |
| Agent import/export | ✅ GitAgent | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Security & Governance

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Input scanning | ✅ Warden | ❌ | ✅ Input guardrails | ✅ Content Safety | ✅ Dual-LLM | 🟡 NeMo | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Tool result scanning | ✅ Warden | ❌ | ✅ Tool guardrails | ✅ Middleware | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Output scanning | ✅ Sentinel | ✅ Sandboxed | ✅ Output guardrails | ✅ Content Safety | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Trust tiers | ✅ 5-tier | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Schema validation & repair | ✅ Sentinel | ❌ | ✅ Pydantic | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| PII filtering | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Config-driven RBAC | ✅ | 🟡 | ❌ | ✅ Entra ID | ✅ | 🟡 Platform | 🟡 AMP | ❌ | ❌ | ❌ | ❌ |
| Per-agent tool permissions | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Audit logging | ✅ | ❌ | ✅ Traces | ✅ | ✅ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Rate limiting | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Sandbox execution | ✅ Containers | ✅ bubblewrap | ✅ | ✅ | ✅ K8s | ❌ | ❌ | 🟡 Docker | ✅ Docker | ❌ | ❌ |
| Zero-trust architecture | ✅ | ❌ | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### Memory & Learning

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Session memory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Episodic memory (7-tier) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Self-improving learnings | ✅ | 🟡 Auto-memory | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Memory scopes (5 levels) | ✅ | ❌ | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Knowledge/RAG (pgvector) | ✅ | ❌ | 🟡 | ✅ | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Memory decay & reinforcement | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Auto-promotion of corrections | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Naive RLHF / self-modification | 🗺️ Native | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Research | ❌ | ❌ |

### Model Routing

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-model support | ✅ | 🟡 Anthropic | 🟡 OpenAI | ✅ Foundry | ✅ | ✅ Portkey | ✅ LiteLLM | ✅ | 🟡 | 🟡 | ✅ |
| Intelligent cost/quality routing | ✅ Scarcity-based | ❌ | ❌ | ❌ | ✅ Dynamic optimizer | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Automatic fallback (429/5xx) | ✅ | ❌ | ❌ | ✅ | ✅ | 🟡 | 🟡 | ✅ | ❌ | ❌ | ✅ |
| Task-type speed bonuses | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Token budget enforcement | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

### Tool Ecosystem

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| MCP support | ✅ via LiteLLM | ✅ | ✅ | ✅ | ✅ Registry | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| AI tool/agent creation (Forge) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| OpenAPI auto-conversion | ✅ via LiteLLM | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Skill marketplace | ✅ | ❌ | ❌ | ✅ Foundry | ✅ 858+ servers | ❌ | ❌ | ✅ ClawHub | ❌ | ❌ | ❌ |

### Observability

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| OTEL tracing | ✅ Phoenix | ✅ | ✅ | ✅ | ✅ Prometheus | ✅ LangSmith | ✅ | ❌ | ❌ | 🟡 | ❌ |
| Prompt management | ✅ PostgreSQL | ❌ | ❌ | ❌ | ❌ | 🟡 LangSmith | ❌ | ❌ | ❌ | ❌ | ❌ |
| Cost tracking | ✅ LiteLLM | ❌ | ❌ | ✅ | ✅ | 🟡 Portkey | ❌ | ❌ | ❌ | ❌ | ✅ |

### Enterprise & Multi-Tenant

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Multi-tenant isolation | 🗺️ | ❌ | ❌ | ✅ | ✅ | ✅ Platform | 🟡 AMP | ❌ | ❌ | ❌ | ❌ |
| SSO / OIDC | ✅ Keycloak + Entra | ✅ Enterprise | ❌ | ✅ Entra ID | ❌ | ✅ Platform | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Namespace-scoped secrets | 🗺️ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Agent marketplace | 🗺️ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |

### What Makes Stronghold Different

Most agent frameworks give you **building blocks** (LangGraph, OpenAI Agents SDK) or a **finished product** (Claude Code, OpenClaw). Stronghold is an **opinionated governance platform** — it ships with a complete agent roster, security scanning at every trust boundary, self-improving memory, and intelligent model routing, all behind swappable protocol interfaces.

**Unique to Stronghold:**
- **Defense-in-depth security** — Warden scans both user input *and* tool results before they enter LLM context. Sentinel enforces policy at every boundary crossing. No other framework scans tool results by default.
- **5-tier trust system** — Tools and agents earn trust through automated validation and operator approval (☠️ → T3 → T2 → T1 → T0). Only MS Agent Framework has comparable trust tiers.
- **Self-improving memory** — Learns from tool-call failures (fail→succeed extraction), auto-promotes corrections after N successful uses, bridges to 7-tier episodic memory with structural weight floors. No other platform combines learning extraction with tiered episodic memory and decay.
- **Scarcity-based model routing** — Cost rises smoothly as provider token pools deplete. No cliffs, no manual rebalancing. Only Archestra has comparable intelligent routing (via a dynamic optimizer).
- **Tournament-based agent evolution** — Agents compete head-to-head on live traffic; winners earn routes. No other framework has this.
- **Protocol-driven DI with zero direct external imports** — Business logic depends only on protocols. LiteLLM, Arize, PostgreSQL — all swappable without touching a single line of business logic.

**Roadmap — Naive RLHF:** Stronghold's builders loop already implements plan → execute → review → learn → iterate with automatic learning extraction and correction promotion. The roadmap wraps a meta-agent around this graph, treating the entire workflow as both a pipeline of agents *and* an agent itself — enabling the graph to modify its own structure (add/remove/reorder nodes, adjust strategy selection, tune scoring weights). Internally called "naive RLHF", this is a native implementation of the [Hyperagents](https://arxiv.org/abs/2603.19461) theoretical construct, built from existing Stronghold primitives under Apache 2.0 with no external dependency on Meta's non-commercial research code.

## License

Apache 2.0 — see [LICENSE](LICENSE).
