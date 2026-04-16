# Feature Comparison — Detailed Analysis

How Stronghold compares to 10 agent frameworks and platforms across 8 categories.

**Compared frameworks:**

| Framework | Type | License | What It Is |
|---|---|---|---|
| [Claude Code](https://claude.ai/code) | Coding agent | Source-available | Anthropic's agentic coding tool with OS-level sandboxing |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Agent SDK | MIT | Production SDK with guardrails, handoffs, and tracing |
| [MS Agent Framework](https://github.com/microsoft/agents) | Enterprise framework | MIT | Microsoft's Semantic Kernel + AutoGen successor, Azure-native |
| [Archestra](https://archestra.ai) | MCP orchestration | AGPL-3.0 | Enterprise MCP gateway with dual-LLM security and K8s runtime |
| [LangGraph](https://github.com/langchain-ai/langgraph) | Orchestration library | MIT | Stateful multi-agent graphs with checkpointing (LangChain) |
| [CrewAI](https://github.com/crewAIInc/crewAI) | Multi-agent framework | MIT | Role-based agent crews with process orchestration |
| [OpenClaw](https://github.com/openclaw/openclaw) | Personal assistant | MIT | 24/7 autonomous agent on your hardware via messaging platforms |
| [Hyperagents](https://arxiv.org/abs/2603.19461) | Research | CC BY-NC-SA | Meta's self-referential self-improving agents (non-commercial) |
| [Deep Agents](https://github.com/langchain-ai/deep-agents) | Agent harness | MIT | Opinionated LangGraph-based coding agent harness |
| [Pi](https://github.com/badlogic/pi) | Agent toolkit | MIT | TypeScript monorepo powering OpenClaw's runtime |

**Legend:** ✅ = Full support | 🟡 = Partial / requires integration | 🗺️ = Roadmapped | ❌ = Not available

---

## 1. Architecture & Deployment

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Open source | ✅ Apache 2.0 | Source-avail. | ✅ MIT | ✅ MIT | ✅ AGPL-3.0 | ✅ MIT | ✅ MIT | ✅ MIT | CC BY-NC-SA | ✅ MIT | ✅ MIT |
| Self-hosted | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Kubernetes native | ✅ | ❌ | ❌ | ✅ | ✅ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Helm charts | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Docker Compose | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Protocol-driven DI | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Language | Python | TS/Rust | Python/TS | .NET/Python | Go | Python/TS | Python | TS | Python | Python | TS |

### Analysis

**Stronghold's position:** Full-stack self-hosted platform with both Docker Compose (dev) and Kubernetes + Helm (production). Protocol-driven DI means every external dependency (LiteLLM, PostgreSQL, Arize) is behind a swappable interface — 20 protocols, zero direct imports in business logic. Ported from Maistro (March 25, 2026) with security-first redesign.

**Closest competitors:**
- **MS Agent Framework** is the only other framework with comparable deployment maturity (K8s, Helm) AND protocol-driven architecture. However, its full feature set is tightly coupled to Azure AI Foundry.
- **Archestra** ships K8s-native with Terraform + Helm but is AGPL-3.0 (copyleft), which limits commercial embedding. Go-based (vs Stronghold's Python).
- Most others (OpenAI Agents SDK, CrewAI, LangGraph, Deep Agents, Pi) are libraries you `pip install` — they provide orchestration primitives, not deployment infrastructure.

**Licensing note:** Stronghold (Apache 2.0) and most MIT-licensed frameworks allow unrestricted commercial use. Archestra's AGPL-3.0 requires derivative works to be open-sourced. Hyperagents' CC BY-NC-SA prohibits commercial use entirely.
