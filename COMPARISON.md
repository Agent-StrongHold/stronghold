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

---

## 2. Multi-Agent Orchestration

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

### Analysis

**Stronghold's position:** Ships 6 production-ready specialist agents (Arbiter, Artificer, Scribe, Ranger, Warden-at-Arms, Forge) — no other framework does this. All orchestration features were ported from Maistro in the initial commit; the Builders 2.0 pipeline (Frank + Mason) and learning strategy were added in the first week (April 1–2, 2026).

**Shipped agent roster** — Every other framework expects you to build your own agents from primitives. Stronghold ships opinionated specialists with defined roles, trust boundaries, and tool permissions. CrewAI's role/goal/backstory pattern is conceptually similar but requires you to define every agent yourself.

**Reasoning strategies** — Stronghold provides 4 generic strategies (direct, react, plan_execute, delegate) that any imported agent can use without writing Python, plus custom strategies for specialists. LangGraph achieves similar flexibility through graph node composition. CrewAI has sequential/hierarchical/consensual process types. MS Agent Framework supports sequential, concurrent, handoff, and group chat patterns.

**Tournament evolution** — Unique to Stronghold. 5–10% of requests run two agents on the same task. Scored by LLM-as-judge, tool success rate, and user feedback. Winners earn routes automatically. No other framework has automated agent competition.

**Dynamic intent creation** — Unique to Stronghold. When an agent is imported with capabilities that don't fit existing intents, the system creates a new intent category from the agent's declared keywords. No manual routing table updates.

**Proactive behavior** — Stronghold's Reactor is a 1000Hz event loop that unifies event-driven, interval, time, and state triggers. OpenClaw has basic cron scheduling. No other framework has a general-purpose proactive agent runtime.

**GitAgent import/export** — Unique to Stronghold. Clone a git repo, run `stronghold agent import`, and the agent's YAML, prompts, memories, tools, and strategy are loaded into the running system. Export round-trips cleanly. No other framework has a portable agent format.

---

## 3. Security & Governance

This is Stronghold's primary differentiator. Security is not a feature — it is the architectural foundation. Every design decision starts with "how can this be exploited?" The entire security stack (Warden, Gate, Sentinel, trust tiers) shipped in the initial commit from Maistro (March 25, 2026), then redesigned with security as the unitary design principle rather than one concern among many.

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

### Analysis

**Stronghold's position:** The only framework where security is the foundational design principle, not an add-on. Three dedicated security components — Warden (threat detection), Sentinel (policy enforcement), Gate (input processing) — cover every trust boundary in the system. All shipped in the initial commit.

**Three-boundary scanning** — Only 4 frameworks scan at all three boundaries (input, tool results, output): Stronghold, OpenAI Agents SDK, MS Agent Framework, and Archestra. The approaches differ significantly:
- **Stronghold:** Warden uses cheap-to-expensive layering (regex → heuristics → LLM) that short-circuits on detection. Sentinel handles policy enforcement as a LiteLLM guardrail plugin. Both scan tool results — indirect prompt injection through tool output is one of the most underestimated attack vectors.
- **OpenAI Agents SDK:** Input/output/tool guardrails run in parallel with agent execution, fail-fast. Clean design but guardrails must be explicitly wired per agent.
- **MS Agent Framework:** Azure AI Content Safety integration with agent middleware pipeline. Strongest when deployed on Azure; less capable standalone.
- **Archestra:** Dual-LLM architecture isolates dangerous tool responses in a security sub-agent. Novel approach to prompt injection prevention.

**Trust tiers** — Only Stronghold and MS Agent Framework have tiered trust. Stronghold's 5-tier system (☠️ Skull → T3 Forged → T2 Community → T1 Installed → T0 Built-in) with earned promotion through automated validation is more granular. Output from the Forge agent starts at ☠️ and must pass security scanning to promote. No tool or agent auto-promotes past T3 without operator approval or tournament evidence.

**Schema validation & repair** — Stronghold's Sentinel doesn't just validate tool-call arguments against MCP schemas — it repairs them. Fuzzy-matches hallucinated field names to real ones, coerces types, applies defaults. Repairs feed back into the learning system. OpenAI Agents SDK validates via Pydantic but doesn't repair.

**Zero-trust** — Stronghold is the only framework designed zero-trust end-to-end: all user input is untrusted, all tool results are untrusted, all agent output is scanned before return. MS Agent Framework and Archestra have partial zero-trust (strong at the boundary, weaker internally).

**OpenClaw security note:** OpenClaw accumulated 138 CVEs in its first 5 months (7 critical, 49 high). A systematic taxonomy paper (arXiv 2603.27517) catalogs 190 security advisories. Nvidia released NemoClaw as a third-party security add-on. Enterprise use without additional hardening is not recommended.

---

## 4. Memory & Learning

| Feature | Stronghold | Claude Code | OpenAI Agents SDK | MS Agent Framework | Archestra | LangGraph | CrewAI | OpenClaw | Hyperagents | Deep Agents | Pi |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Session memory | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Episodic memory (7-tier) | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Self-improving learnings | ✅ | 🟡 Auto-memory | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Memory scopes (5 levels) | ✅ | ❌ | ❌ | 🟡 | ❌ | ❌ | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Knowledge/RAG (pgvector) | ✅ | ❌ | 🟡 | ✅ | ❌ | 🟡 | 🟡 | ❌ | ❌ | ❌ | ❌ |
| Memory decay & reinforcement | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Auto-promotion of corrections | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| RASO (self-modifying agent graph) | 🗺️ Native | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ Research | ❌ | ❌ |

### Analysis

**Stronghold's position:** Memory is where Stronghold is most differentiated. No other platform combines learning extraction, tiered episodic memory with decay, 5-level scoping, and auto-promotion of corrections. The learning store and episodic memory were ported from Maistro in the initial commit; the builders learning strategy (repo recon + self-diagnosis) was added April 2, 2026.

**7-tier episodic memory** — Unique to Stronghold. Memories have structural weight bounds by tier: observations can decay to zero, but regrets can never drop below 0.6, and wisdom (≥0.9) is near-permanent. This means the system structurally cannot forget its worst mistakes or most important lessons. No other framework has tiered memory with enforced weight floors.

**Self-improving learnings** — Stronghold extracts fail→succeed patterns from tool-call history automatically. When a tool call fails with args A and succeeds with args B, the system stores the correction with trigger keywords. After N successful injections, the correction auto-promotes to a permanent prompt addition and optionally bridges to episodic memory (LESSON tier). Closest comparisons:
- **Claude Code** has auto-memory that saves build commands and debugging insights across sessions, but these are static notes, not extracted from failure patterns.
- **Hyperagents** has the most advanced self-improvement (metacognitive self-modification where the improvement mechanism itself is editable), but it's research code under CC BY-NC-SA — non-commercial, not importable as a library.

**5 memory scopes** — global (all agents, all users) → team (same domain) → user (all agents, one user) → agent (one agent) → session (one conversation). Retrieval is a single query ranked by `similarity(content, query) * weight` with scope filtering. MS Agent Framework has pluggable memory backends (Mem0, Redis, Neo4j) but no structured scope hierarchy. CrewAI has custom memory interfaces but less documented.

**Memory decay & reinforcement** — Unique to Stronghold. Memories decay without reinforcement (observations fade, hypotheses weaken). Reinforced memories gain weight. This prevents unbounded memory growth while preserving structurally important knowledge. No other framework implements automatic decay.

**RASO (Reflexive Agentic Self-Optimization)** — Roadmapped. Wraps a meta-agent around the builders loop graph so it can modify its own structure. This concept was on Stronghold's roadmap before Meta published the Hyperagents paper; Hyperagents has since informed the renewed design. Direction shifted April 16, 2026. Previously called "naive RLHF" internally — renamed because there's no human feedback in the loop, only agent feedback from tournaments, learning extraction, and quality gates.
