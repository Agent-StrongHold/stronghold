# Stronghold Architecture

**Version:** 0.1.0-draft
**Date:** 2026-03-25
**License:** Apache 2.0
**Status:** Design — no implementation yet

---

## 1. What Stronghold Is

Stronghold is an open-source, self-hosted agent governance platform. It wraps any LLM in a secure execution harness with intelligent routing, self-improving memory, autonomous operation, and zero-trust security.

It is extracted from a private homelab AI gateway (Project mAIstro / Conductor) but redesigned from first principles as a clean, enterprise-ready platform.

**Core principle: All input is untrusted. All tool output is untrusted. Trust is earned, not assumed.**

### 1.1 What Makes It Different

Eight innovations preserved from the Conductor codebase, each validated against the patterns in "Agentic Design Patterns" (Gulli, 2026):

1. **Scarcity-based model routing** — `score = quality^(qw*p) / (1/ln(remaining_tokens))^cw`. Cost rises smoothly as provider tokens are consumed. No cliffs, no manual rebalancing. (ADP §8.2: "Optimization is architecture")
2. **Self-improving memory** — learns from tool-call failures (fail→succeed extraction), auto-promotes corrections after N hits, bridges to permanent episodic memory. (ADP §6.2: "Learning means updating prompts, not retraining")
3. **7-tier episodic memory** — regrets (weight ≥0.6) are structurally unforgettable. Wisdom (≥0.9) survives across versions. (ADP §6.1: "Bad memory retrieval is worse than no memory")
4. **Defense-in-depth security** — Warden (threat detection) + Sentinel (policy enforcement) at every trust boundary. (ADP §8.4: "No single guardrail is enough")
5. **Skill Forge** — AI creates its own tools, validates via security scanner, output starts at ☠️ trust tier. (ADP §5.5: "Tool use enables environmental interaction")
6. **Multi-intent parallel dispatch** — compound requests are split by the Conduit and dispatched to specialist agents in parallel. Each agent gets a scoped subtask, not the full compound request. The Conduit aggregates results. (ADP §5.2: "Routing is both intelligence and policy", §5.3: "Parallelization")
7. **Task-type-aware speed bonuses** — voice gets speed weight, code gets quality weight. (ADP §8.2: "Resource-aware optimization")
8. **Tournament-based agent evolution** — agents compete head-to-head, winners earn routes, losers get demoted. Dynamic intent creation on agent import. (ADP §6.2: "Bounded adaptation with evaluation before rollout")

### 1.2 Design Principles

- **Agents are data, not processes.** An agent is rows in PostgreSQL, prompts in PostgreSQL, vectors in pgvector. The runtime is shared. (ADP §5.7: "Agent composition, not agent proliferation")
- **Every external dependency behind a protocol.** LiteLLM, Arize, PostgreSQL — all swappable. (ADP §10: "Make control flow visible")
- **The model proposes, the runtime executes.** LLMs suggest tool calls. Sentinel validates and dispatches. The agent never directly touches the outside world. (ADP §5.5: "Execution is external to the model")
- **Security at every boundary, not just the front door.** Warden scans untrusted ingress. Sentinel enforces policy everywhere. (ADP §8.4: "Safety is layered system controls")

---

## 2. Agent Architecture

### 2.1 What Is An Agent

An agent is a unit of configuration that determines behavior when combined with the shared runtime:

- **Identity** (agent.yaml + SOUL.md) — who it is, what it can do
- **Reasoning strategy** — how it thinks (react, plan-execute, classify-only, direct, delegate, or custom container)
- **Scoped memory** — its own learnings, episodic memories, knowledge, isolated by default
- **Security boundary** — its own Warden rules and Sentinel policies
- **Tool permissions** — which MCP tools it can access, enforced by LiteLLM per-key

There is no agent lifecycle. Agents don't start or stop. They exist as data. The runtime fetches their config from a prompt cache (LRU, evict-on-full) when a request arrives.

### 2.2 Agent Definition Format (GitAgent-Compatible)

```
my-agent/
├── agent.yaml              # REQUIRED — manifest
├── SOUL.md                 # REQUIRED — system prompt / personality
├── RULES.md                # Hard constraints (must-always / must-never)
├── skills/                 # SKILL.md files
├── tools/                  # MCP-compatible tool definitions
├── memory/                 # Seed memories (imported to pgvector)
├── knowledge/              # Reference docs (chunked + embedded for RAG)
├── strategy.py             # Custom deterministic logic (optional, containerized if untrusted)
├── Dockerfile              # For custom strategy containers (optional)
└── agents/                 # Sub-agent definitions (recursive)
```

Only agent.yaml and SOUL.md are required. Everything else is optional. Import/export round-trips cleanly.

### 2.3 Agent Identity

```yaml
# agent.yaml
spec_version: "0.1.0"
name: artificer
version: 1.0.0
description: Code and engineering specialist

soul: SOUL.md

reasoning:
  strategy: plan_execute          # direct | react | plan_execute | delegate | custom
  max_rounds: 10
  review_after_each: true

model: auto
model_fallbacks: [mistral-large, gemini-2.5-pro]
model_constraints:
  temperature: 0.3
  max_tokens: 4096

tools:
  - file_ops
  - shell
  - test_runner
  - lint_runner
  - git

skills: []

memory:
  learnings: true
  episodic: true
  knowledge: true
  session: true
  shared: false
  scope: agent                    # default scope for new memories

rules: RULES.md
trust_tier: t1

permissions:
  max_tool_calls_per_request: 20
  rate_limit: 60/minute

delegation_mode: none
sub_agents:
  - artificer-planner
  - artificer-coder
  - artificer-reviewer
  - artificer-debugger

proactive:
  heartbeat: null
  events: []
  cron: []
```

### 2.4 Agent Roster (Shipped With Stronghold)

| Agent | Strategy | Tools | Trust | Purpose |
|-------|----------|-------|-------|---------|
| **Arbiter** | delegate | none | t0 | Triages ambiguous requests. Sees all agent identities and memory summaries. Cannot act directly. |
| **Ranger** | react | web_search, database_query, knowledge_search | t1, untrusted output | Read-only information retrieval. Everything returned is Warden-scanned. |
| **Artificer** | plan_execute | file_ops, shell, test_runner, lint_runner, git | t1 | Code/engineering. Sub-agents: planner, coder, reviewer, debugger. |
| **Scribe** | plan_execute | file_ops | t1 | Writing/creative. Committee: researcher, drafter, critic, advocate, editor. |
| **Warden-at-Arms** | react | ha_control, ha_list_devices, ha_notify, api_call, runbook_execute | t1 elevated | Real-world interaction. API surface discovery on initialization. |
| **Forge** | react | file_ops, scanner, schema_validator, test_executor, prompt_manager | t1 elevated | Creates tools and agents. Output starts at ☠️ tier. Iterates until minimum viability. |

### 2.5 Reasoning Strategies

**Generic (no custom Python, any imported agent can use):**

| Strategy | Behavior | Lines |
|----------|----------|-------|
| `direct` | Single LLM call, no tools. Chat responses. | ~15 |
| `react` | LLM → tool calls → execute → feed back → repeat (max N rounds). | ~50 |
| `plan_execute` | Plan → decompose → execute subtasks via sub-agents → review. | ~70 |
| `delegate` | Classify intent → route to sub-agent. The Arbiter's brain. | ~20 |

**Custom (Python, shipped with Stronghold or containerized for untrusted):**

| Strategy | Agent | What's Deterministic |
|----------|-------|---------------------|
| Forge strategy | Forge | generate → scan → validate schema → test → iterate loop |
| Artificer strategy | Artificer | plan → code → run pytest → check exit code → review |
| Scribe strategy | Scribe | research → draft → critique → defend → edit committee |
| API discovery | Warden-at-Arms | fetch OpenAPI → parse → classify risk → test → generate skills |

Custom strategies from untrusted sources run in containers. The container is an A2A endpoint — receives a task, calls back to Stronghold for LLM/tools/memory, returns a result. Stronghold manages the container lifecycle.

### 2.6 Routing: Conduit + Tournaments

**Default routing:** Intent → agent lookup table. The classifier produces a task_type, the table maps it to an agent.

**Tournament evolution:** 5-10% of requests run two agents on the same task. Score both (LLM-as-judge, tool success rate, user feedback, trace annotation). Track Elo/win-rate. If a challenger consistently outscores the incumbent, auto-promote.

**Multi-intent parallel dispatch:** When the classifier detects multiple intents in a single request ("turn on the fan and write a poem about it"), the Conduit:

1. Splits the request into scoped subtasks — one per detected intent
2. Dispatches each subtask to the appropriate specialist agent **in parallel** (no dependency between them)
3. Each agent receives only its subtask, not the full compound request — Scribe gets "write a poem about a fan", Warden-at-Arms gets "turn on the fan"
4. Agents execute independently with their own tools, memory, and trust boundaries
5. Conduit aggregates all results into a single response
6. If any subtask fails, the Conduit reports partial success — other subtasks are not affected

This is architecturally different from Conductor's approach (merge all tools into one agent's context). Parallel dispatch preserves agent isolation: the Scribe never sees HA tools, the Warden-at-Arms never sees the poem request. Context windows stay focused, permission boundaries stay intact.

**Dynamic intent creation:** When an agent is imported with capabilities that don't fit existing intents, the system creates a new intent category from the agent's declared keywords. The imported agent becomes the default handler.

### 2.7 Execution Modes

| Mode | Behavior | Trigger |
|------|----------|---------|
| `best_effort` | Try once/twice, return what you have. Default for chat. | Chat input |
| `persistent` | Keep working until done or token budget exhausted. Retry with different approaches. | Form/API with budget |
| `supervised` | Same as persistent but pauses at decision points for user confirmation. | Form/API with confirmation flag |

Budget tracked via LiteLLM cost tracking. Sentinel checks remaining budget before each LLM call.

### 2.8 Inter-Agent Communication

A2A-shaped messages for all delegation:

```python
@dataclass
class AgentTask:
    id: str
    from_agent: str
    to_agent: str
    messages: list[dict]
    execution_mode: ExecutionMode
    token_budget: float | None
    status: str              # submitted | working | input-required | completed | failed
    result: str | None
    trace_id: str
```

Transport: function calls in-process. A2A JSON over HTTP when agents become separate services (enterprise K8s deployment).

### 2.9 Proactive Behavior (Reactor)

All proactive behavior flows through a single **Reactor** — a 1000Hz event loop that unifies event-driven, interval-based, and time-based triggers into one evaluation system.

**Core insight:** A trigger is `when CONDITION, do ACTION`. The condition can be an event (`tool_call == ha_control`), time (`05:45`), or interval (`every 30 minutes`). These are the same pattern with different predicates. One loop evaluates all of them.

#### Reactor Loop

The loop does **no I/O**. It drains an event queue, evaluates trigger conditions (pure logic), and spawns async tasks for matches. Benchmarked at 0.46% of 1 core with 100 triggers at 1000Hz. 35us average blocking latency.

```
┌───────────────────────────────────────┐
│          Reactor (1000Hz tick)         │
│  1. Drain event queue                 │
│  2. For each trigger: condition match?│
│     → blocking: resolve future inline │
│     → async: spawn worker task        │
│  3. sleep(1ms)                        │
└───────────────┬───────────────────────┘
                │ spawns
                ▼
┌───────────────────────────────────────┐
│         Worker Tasks (async)           │
│  agent.handle(), health checks, etc.  │
└───────────────────────────────────────┘
```

#### Trigger Modes

| Mode | Condition | Example |
|------|-----------|---------|
| `event` | Matches event name (regex) | `pre_tool_call`, `quota_exceeded`, `warden_alert` |
| `interval` | Elapsed time since last fire | Every 30 minutes (with optional PRNG jitter ±20%) |
| `time` | Clock matches HH:MM | `05:45` daily |
| `state` | Callable returns true | `quota.usage_pct > 80` |

#### Blocking vs Async

- **Blocking triggers** resolve the emitter's future inline (≤1ms). Used for gates: `pre_tool_call` → allow/deny. The request pipeline awaits the result.
- **Async triggers** spawn a task and return immediately. Used for side effects: learning extraction, health checks, notifications.

#### Circuit Breaker

Per-trigger failure tracking. Disable after N consecutive failures. Alert to audit log. Re-enable via admin API or restart.

#### Why a Tick Loop (Not Pure Event-Driven)

A pure `await queue.get()` loop uses zero CPU when idle but trusts all emitters to be reliable. The tick loop re-evaluates every condition every millisecond regardless of emitter health. If an emitter crashes, interval/time/state triggers still fire because the loop checks the clock itself. The 0.46% CPU is the cheapest reliability guarantee in the system.

#### Integration

All proactive triggers ultimately invoke `agent.handle()` with a system-generated message. Same pipeline, different input source. Event sources:
- **Request pipeline** (`route_request`): `pre_classify`, `post_classify`, `pre_tool_call`, `post_tool_call`, `post_response`
- **Internal clock**: interval and time triggers evaluated each tick
- **State monitors**: quota pressure, Warden alerts, agent import events

---

## 3. Security Architecture

### 3.1 Threat Baseline

`/root/conductor_security.md` documents 20 known gaps and 50 untouched security concerns in the current Conductor stack. Stronghold must improve on every one.

### 3.2 Warden (Threat Detection)

**Job:** Detect hostile content in untrusted data entering the system.
**Runs at exactly two points:** user input and tool results.
**Cannot:** call tools, access memory, invoke inference (intentionally incapable).

Three layers (cheap to expensive, short-circuit on detection):
1. **Regex patterns** — known attack shapes (prompt injection, role hijacking, system prompt extraction). Zero cost, sub-millisecond.
2. **Heuristic scoring** — instruction-density detection in tool results. Lightweight statistical check.
3. **LLM classification** — novel threat detection. Only triggered when heuristics are ambiguous. Cheap/fast model. Classification prompt managed in PostgreSQL prompt library.

Verdict: `clean | sanitized | blocked` with structured flags.

**Addresses Conductor gaps:** #1-6 (prompt injection), #3 (tool result injection), #10 (tool results fed to LLM unredacted).

### 3.3 Sentinel (Policy Enforcement)

**Job:** Enforce correctness and policy at every boundary crossing.
**Implementation:** in-process pre/post wrap around every tool /
playbook execution in `agents/strategies/react.py:140-211`. (Earlier
drafts described this as a LiteLLM guardrail plugin; the code has
always run in-process — see ADR-K8S-020.)

Capabilities:
- **Schema validation** — validate LLM tool_call arguments against the
  declared inputSchema (from `@tool` or `@playbook`).
- **Schema repair** — fuzzy match hallucinated arg names to real field
  names, coerce types, apply defaults. Repairs feed back into learnings.
- **Policy enforcement** — per-agent tool permissions via the Casbin
  tool policy layer (ADR-K8S-019), evaluated in-process. Replaces the
  earlier LiteLLM per-key scheme.
- **Token optimization** — compress bloated tool results before
  re-injection into LLM context. Briefs from playbooks (§5.2) hit the
  size budget server-side, so post-call compression is mostly a safety
  net for legacy tools and `*_raw` escape hatches.
- **Audit logging** — every boundary crossing logged to PostgreSQL +
  Arize trace span.
- **Rate limiting** — Redis-backed `InMemoryRateLimiter` / distributed
  rate limiter in Stronghold (not LiteLLM).
- **PII filtering** — scan outbound responses for leaked API keys,
  internal IPs, system prompt content.

**Addresses Conductor gaps:** #4 (no rate limiting), #5 (JWT audience), #6 (hardcoded roles), #12 (infra_action no allowlist), #13 (CoinSwarm spawn no bound), #22 (no body size limit), #29 (routing metadata leaks), #31 (error responses unfiltered), #47 (skill import from any URL).

### 3.4 The Gate (Input Processing)

**Job:** Process user input before it reaches the Conduit.
**Not an agent.** Infrastructure with limited capabilities.

Flow:
1. **Warden scan** — malicious intent detection
2. **Sanitize** — strip zero-width chars, normalize unicode, escape injection fragments
3. **If persistent/supervised mode:** Query Improver (good model) — summarize request, identify gaps, generate 1-5 clarifying questions (a,b,c,d,other), return to user for correction
4. **If chat/best_effort:** silent sanitize, pass through immediately
5. Pass safe, improved prompt to Conduit

**Addresses Conductor gaps:** #4 (classifier manipulation via keyword stuffing), #22 (no body size limit), #34 (client-provided session_id).

### 3.5 Trust Tiers

| Tier | Name | Description | Who Creates |
|------|------|-------------|-------------|
| ☠️ | Skull | In the Forge. Under construction. Cannot be used. | Forge agent |
| T3 | Forged | Passed Forge QA. Sandboxed. Read-only tools only. | Forge → promotion |
| T2 | Community | Marketplace install or operator-approved. Standard policies. | Import from URL |
| T1 | Installed | Operator-vetted. Full tool access per agent config. | GitAgent import, admin-approved |
| T0 | Built-in | Shipped with Stronghold. Core trust. | Stronghold maintainers |

Promotion path: ☠️ → T3 (Forge QA passes) → T2 (N successful uses, no Warden flags) → T1 (operator approval). Never auto-promotes to T0.

### 3.6 Security Concern Traceability

Every concern from `conductor_security.md` §17 mapped to a Stronghold mitigation:

**Prompt Injection (#1-6):** Warden regex+LLM at user input ingress. Warden scan on tool results before LLM re-injection. Memory scope isolation prevents poisoned learnings from leaking cross-user.

**Cross-User Data Leakage (#7-11):** Memory scoped by (global/team/user/agent/session). Retrieval queries filter by scope. Arize handles trace RBAC (Enterprise) or is single-tenant (Phoenix).

**Privilege Escalation (#12-17):** Sentinel schema validation against MCP inputSchema. Per-agent tool permissions via LiteLLM per-key config. Execution modes with token budgets. Config-driven permission tables, not hardcoded roles.

**Shared Credentials (#18-21):** K8s secrets manager (compatible with Vault, Vaultwarden). Per-agent credentials. No hardcoded keys in source. Service-to-service JWT signing (LiteLLM's Zero Trust JWT).

**DoS (#22-28):** Sentinel rate limiting via LiteLLM. Request body size limits at Gate. Circuit breaker pattern for failed backends. Connection pooling via asyncpg (not per-call SQLite connections).

**Information Disclosure (#29-33):** Sentinel PII filter on outbound responses. No routing metadata in production responses (debug mode only). Error responses sanitized before return.

**Session Integrity (#34-37):** Session IDs validated by Sentinel. User-scoped sessions enforced. Session revocation via API.

**Supply Chain (#38-41):** Pinned dependencies with hash verification. Docker image digest pinning. Checksummed binary downloads in Dockerfiles.

**Crypto (#42-44):** JWT audience verification enabled (Entra ID and Keycloak both enforce). CSRF protection via SameSite cookies. Constant-time token comparison for static keys.

---

## 4. Memory Architecture

### 4.1 Storage

Single PostgreSQL instance with pgvector extension. No SQLite.

```sql
-- stronghold schema
agents              -- agent registry (identity, config, trust tier)
learnings           -- self-improving corrections (per-agent scoped)
sessions            -- conversation history (per-user scoped)
quota_usage         -- token tracking (migrated from SQLite)
audit_log           -- Sentinel audit trail
permissions         -- RBAC config cache
tournaments         -- agent head-to-head results

-- memories schema (pgvector)
episodic            -- 7-tier weighted memories
knowledge           -- RAG chunks + embeddings
```

### 4.2 Memory Scopes

| Scope | Visibility | Example |
|-------|-----------|---------|
| `global` | All agents, all users | "GDPR means General Data Protection Regulation" |
| `team` | Agents in the same domain | "The data pipeline team uses Airflow" |
| `user` | All agents, for this specific user | "Blake prefers concise responses" |
| `agent` | Only this agent | "entity_id for the fan is fan.bedroom_lamp" |
| `session` | Only this conversation | "The user wants bullet points" |

Retrieval: `global + team (if applicable) + user (from auth) + agent (from agent_id) + session (if session_id)`. One query, ranked by `similarity(content, query) * weight`.

### 4.3 Episodic Memory Tiers

| Tier | Weight Bounds | Pruning | Purpose |
|------|--------------|---------|---------|
| Observation | 0.1 – 0.5 | Can decay to zero | Neutral notices |
| Hypothesis | 0.2 – 0.6 | Can decay to zero | What-if analysis |
| Opinion | 0.3 – 0.8 | Slow decay | Beliefs with confidence |
| Lesson | 0.5 – 0.9 | Resistant to decay | Actionable takeaways |
| Regret | 0.6 – 1.0 | **Cannot drop below 0.6** | Mistakes to never repeat |
| Affirmation | 0.6 – 1.0 | **Cannot drop below 0.6** | Wins to repeat |
| Wisdom | 0.9 – 1.0 | **Near-permanent** | Institutional knowledge |

### 4.4 Self-Improving Memory Loop

```
Request arrives with user text
  → Retrieve relevant learnings (keyword + embedding hybrid search)
  → Inject into system prompt
  → LLM generates response (may include tool calls)
  → Tool call fails → retry with different args → succeeds
  → Learning extractor: "tool X fails with arg A, succeeds with arg B"
  → Store as agent-scoped learning with trigger keywords
  → After N successful injections → auto-promote to permanent prompt
  → Optionally bridge to episodic memory (LESSON tier)
```

---

## 5. Tool Architecture

### 5.1 MCP — Stronghold as Server, Gateway, and Orchestrator

Stronghold serves MCP directly. LiteLLM is LLM-proxy-only — model
routing, per-key spend tracking, fallback on 429/5xx. The MCP subsystem
lives in `src/stronghold/mcp_server/` and is mounted at `/mcp/v1/` on
the Stronghold-API pod (Streamable HTTP primary, stdio for local
clients). See ADR-K8S-020 and ADR-K8S-024.

Three roles from one pod:

- **Server** — exposes `tools/list`, `tools/call` (and `prompts/*`,
  `resources/*` as they come online). Tools surfaced are agent-oriented
  **playbooks** that compose multiple backend API calls server-side and
  return a markdown **Brief** shaped for reasoning LLMs, not raw JSON.
  See §5.2.
- **Gateway** — proxies `*_raw` calls to external MCP guest servers or
  upstream REST APIs. Governance at every hop: Casbin tool policy
  check, Sentinel schema repair, credential injection from the vault,
  Warden output scan, Phoenix audit log.
- **Orchestrator** — agent strategies (`react`, `plan_execute`,
  `delegate`) compose multi-playbook chains. The model proposes; the
  runtime executes. The agent loop in `agents/strategies/react.py`
  calls playbooks through the same `tool_executor` callback it used
  for thin tools — no wire change.

**Authentication.** OAuth 2.1 + PKCE + DCR for desktop clients
(discovery at `/.well-known/oauth-authorization-server`). Static API
tokens are the fallback. Per-user tokens carry `tenant_id` + `user_id`
+ `scopes`, propagated into every `PlaybookContext`.

**Tool shape.** Target ≤20 primary playbooks. Task-oriented names
(`review_pull_request(url, focus)`, not `get_pr` + 5 calls), NL-friendly
inputs, markdown Briefs under 6 KB (12 KB with `allow_large=True`),
inline next-action hints, dry-run for writes, one `*_raw` escape hatch
per integration.

### 5.2 Playbook + Brief

Every playbook is an async function registered via `@playbook(name, …)`
that accepts `(inputs: dict, ctx: PlaybookContext)` and returns a
`Brief`. The `Brief` dataclass (`src/stronghold/playbooks/brief.py`)
renders to markdown with:

- `title` (H1)
- `summary` (≤400 chars, the TL;DR)
- `sections` (named body sections, each Warden-scanned)
- `flags` (warnings the reasoner should notice — merge conflicts,
  failing checks, prompt injection in upstream content)
- `next_actions` (suggested follow-up playbook calls with args and a
  one-line reason)
- `source_calls` (audit trail of backend operations composed)

The adapter `PlaybookToolExecutor` translates `Brief.to_markdown()` into
`ToolResult.content` so the existing agent loop (`react.py:165`) sees a
playbook as any other tool.

**Escape hatches.** `github_raw`, `fs_raw`, `exec_raw`, `mcp_raw` exist
for the 1% of cases no playbook covers. Gated by Casbin policy, T1
trust tier, and per-agent allowlist. Audit-logged.

**Sentinel.** Pre-call schema validation/repair and post-call Warden
+ PII + token optimization run **in-process** around every playbook
execution (they always have — the LiteLLM-guardrail framing in earlier
drafts never matched the actual code path at `react.py:140-211`).

### 5.3 Tool Backends

| Backend | Protocol | Provided By |
|---------|----------|-------------|
| Playbooks | In-process | `src/stronghold/playbooks/` — agent-oriented compose + Brief |
| Escape hatches | In-process | `github_raw`, `fs_raw`, `exec_raw`, `mcp_raw` |
| MCP guest servers | MCP native proxy | Stronghold gateway proxies via `mcp_raw` (community servers) |
| Kubernetes | In-process / MCP | Future playbooks + external K8s MCP servers |
| Legacy HTTP | Direct HTTP | Wrapped by playbooks' shared clients (e.g. GitHubClient) |

### 5.4 Forge Tool/Agent Creation

The Forge agent iterates on created artifacts until they pass minimum viability:

```
Generate → Scanner (security) → Schema validator → Test with sample inputs
  → Test with empty inputs → Test with adversarial inputs
  → All pass → Promote from ☠️ to T3
  → Any fail → Fix and retry (max 10 rounds)
```

Forge output can never auto-promote past T3. Higher tiers require automated tournament evidence or human approval.

---

## 6. Authentication & Authorization

### 6.1 Auth Providers (Protocol-Based)

```python
class AuthProvider(Protocol):
    async def authenticate(self, authorization: str | None,
                           headers: dict | None = None) -> AuthContext: ...
```

| Provider | Use Case | Claims |
|----------|----------|--------|
| Keycloak OIDC | Homelab, open-source default | realm_access.roles |
| Entra ID | Enterprise (Microsoft-shop customers) | roles (app roles) |
| Static API key | Service-to-service, backward compat | Maps to system admin context |
| OpenWebUI headers | Thin client passthrough | X-OpenWebUI-User-* headers |

### 6.2 RBAC (Config-Driven)

```yaml
# permissions.yaml
roles:
  admin:
    tools: ["*"]
    agents: ["*"]
  engineer:
    tools: [web_search, file_ops, shell, git, test_runner]
    agents: [artificer, ranger, scribe]
  operator:
    tools: [ha_control, ha_list_devices, k8s_get_pods, k8s_scale]
    agents: [warden-at-arms, ranger]
    require_confirmation: [k8s_scale]
  viewer:
    tools: [web_search]
    agents: [ranger, scribe]

role_mapping:
  keycloak:
    admin: admin
    parent: operator
    kid: viewer
  entra_id:
    Stronghold.Admin: admin
    Stronghold.Engineer: engineer
    Stronghold.Operator: operator
    Stronghold.Viewer: viewer
```

**Addresses Conductor gap #6:** roles are config, not code. No `_USER_ROLES` dict.

---

## 7. Observability

### 7.1 Split Responsibilities

| Concern | Backend | Why |
|---------|---------|-----|
| Prompt management | PostgreSQL (stronghold.prompts table) | Versioning, labels, config metadata — all just columns. No external dependency. |
| Traces + scoring (small team / demo) | Arize Phoenix (OSS, 2 containers) | OTEL-native, lightweight, free |
| Traces + scoring (enterprise) | Arize Enterprise | RBAC, SSO, team scoping, audit logs, cost tracking, dashboards |
| LLM call telemetry | LiteLLM callbacks → Phoenix or Arize | Cost, tokens, latency per call |
| Audit trail | PostgreSQL (stronghold.audit_log) | Queryable, persistent, not dependent on external service |

### 7.2 Prompt Storage (PostgreSQL-Native)

Prompts are stored in PostgreSQL, not Langfuse. A prompt is a versioned text blob with structured metadata:

```sql
CREATE TABLE prompts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,            -- "agent.artificer.soul"
    version     INTEGER NOT NULL,
    label       TEXT,                     -- "production", "staging", NULL
    content     TEXT NOT NULL,            -- the prompt text
    config      JSONB DEFAULT '{}',       -- structured metadata
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  TEXT DEFAULT 'system',
    UNIQUE(name, version),
    UNIQUE(name, label)
);
```

API endpoints for prompt management:
- `GET /api/prompts` — list all prompts
- `GET /api/prompts/{name}` — get prompt (label=production default)
- `GET /api/prompts/{name}/versions` — version history
- `PUT /api/prompts/{name}` — create new version
- `POST /api/prompts/{name}/promote` — move label to a version

This replaces Langfuse for prompt management. No external dependency. Multi-tenant via tenant_id column. Hot-reload via PostgreSQL LISTEN/NOTIFY or poll updated_at.

### 7.3 Protocol Layer

Every observability component behind a protocol:

| Protocol | Primary Impl | Fallback |
|----------|-------------|----------|
| `PromptManager` | PostgreSQL (stronghold.prompts) | Filesystem (YAML/MD for dev), Langfuse (legacy adapter) |
| `TracingBackend` | Arize Phoenix (small team) or Arize Enterprise (enterprise) | PostgreSQL raw, noop |
| `LLMClient` → callback | LiteLLM → Phoenix/Arize | LiteLLM → stdout |

### 7.4 Logging

Stronghold uses Python's standard `logging` module via `dictConfig`, configured once at API process startup. Logging is **distinct from tracing** (§7.5): logs are line-oriented, leveled, human-readable; traces are structured, hierarchical, attribute-rich.

| Module | Role |
|--------|------|
| `stronghold.log_config` | `dictConfig` with `RunIdFilter`, console handler, named loggers per subsystem (`stronghold.builders.tdd`, `stronghold.builders.workflow`, etc.). `configure_logging()` is idempotent and called from the FastAPI `lifespan` hook. |
| `stronghold.log_context` | `RunLoggerAdapter(logging.LoggerAdapter)` — attaches `run_id` to every record's `extra` field for the duration of a workflow scope. Used at the top of long-running async workflows so log lines auto-attribute without manual interpolation. |

Format: `%(asctime)s %(levelname)-8s %(name)s [run_id=%(run_id)s] %(message)s`. The `RunIdFilter` injects `run_id="-"` for records emitted outside a workflow scope (libraries, framework code) so the format string never `KeyError`s.

Why a `LoggerAdapter` rather than `contextvars.ContextVar`: simpler, scoped explicitly to the workflow function, no asyncio leakage gotchas. Workflow code already has `run` available everywhere it would log, so threading the adapter is cheap.

JSON formatter / log shipping to an aggregator are intentionally out of scope at this layer — logs go to stdout, `docker logs`/`journalctl` collect them.

### 7.5 Tracing Architecture

Every request is a trace. Every boundary crossing is a span:

```
trace (user_id, session_id, agent)
├── warden.user_input
├── sentinel.user_to_system
├── gate.query_improve (if persistent mode)
├── conduit.classify
├── conduit.route
├── agent.{name}.handle
│   ├── prompt.build (soul + tools + learnings + episodic)
│   ├── sentinel.system_to_llm
│   ├── llm_call_0 (LiteLLM callback fills details)
│   ├── sentinel.llm_to_system
│   ├── tool.{name} (via Sentinel guardrail)
│   │   ├── sentinel.validate_args
│   │   ├── sentinel.repair (if needed)
│   │   ├── execution
│   │   ├── warden.tool_result
│   │   └── sentinel.token_optimize
│   ├── llm_call_1
│   ├── learning.extraction
│   └── sentinel.system_to_user
└── trace.end
```

---

## 8. Protocol Layer

Every external dependency behind a protocol interface. Implementations are swappable without touching business logic.

| Protocol | Methods | Current Impl | Swap Target |
|----------|---------|-------------|-------------|
| `ModelProxy` | complete(), stream(), list_models() | LiteLLM | direct provider SDKs, alternative gateways |
| `ToolGateway` | list_tools(), call_tool(), register_*() | LiteLLM MCP gateway | Kong, alternative MCP gateways, standalone |
| `AuthProvider` | authenticate() | Keycloak, Entra ID | Any OIDC provider |
| `PromptManager` | get(), get_with_config(), upsert() | PostgreSQL (stronghold.prompts) | Langfuse (legacy adapter) |
| `TracingBackend` | create_trace() → Trace, Span | Arize Enterprise | Phoenix, PostgreSQL, noop |
| `DataStore` | execute(), insert() | PostgreSQL (asyncpg) | SQLite (aiosqlite) for local dev |
| `LearningStore` | store(), find_relevant(), mark_used(), check_auto_promotions() | PostgreSQL | — |
| `EpisodicStore` | store(), retrieve(), reinforce() | PostgreSQL + pgvector | — |
| `SessionStore` | get_history(), append_messages() | PostgreSQL | Redis |
| `QuotaTracker` | record_usage(), get_usage_pct() | PostgreSQL | LiteLLM native spend tracking |

---

## 9. Deployment

### 9.1 Target: Kubernetes

Clean enterprise production K8s deployment. No enterprise license required for single-team use.

### 9.2 Components

| Component | Type | Notes |
|-----------|------|-------|
| Stronghold API | Deployment | FastAPI, the main application |
| PostgreSQL + pgvector | StatefulSet | Single instance, multiple schemas |
| Arize Phoenix (small team) or Arize Enterprise | Deployment | Traces + dashboards |
| LiteLLM | Deployment | Model proxy + MCP gateway + tool policy |
| Arize | Managed or self-hosted | Trace storage + dashboards |
| MCP servers | Deployments (1 per tool backend) | HA, K8s, filesystem, etc. |
| Custom agent containers | Deployments (optional) | For teams running containerized strategies |

### 9.3 Secrets

K8s secret manager (primary). Compatible with HashiCorp Vault and Vaultwarden. No hardcoded keys in source or config files.

### 9.4 Multi-Tenant Isolation

Per-tenant K8s namespace. Each namespace gets:
- Own LiteLLM API keys (tool permissions scoped)
- Own Arize project/space (trace isolation via RBAC)
- Memory scoped by tenant_id in shared PostgreSQL, or separate PostgreSQL per namespace

---

## 10. Import / Export

### 10.1 GitAgent Import

```
git clone → stronghold agent import ./my-agent/
```

| Source | Destination | Purpose |
|--------|------------|---------|
| agent.yaml | PostgreSQL agents table | Registry |
| SOUL.md | PostgreSQL prompt: agent.{name}.soul | Hot-swappable system prompt |
| RULES.md | PostgreSQL prompt + Warden rule set | Security policy |
| skills/*.md | PostgreSQL prompts: skill.{name} | Tool system prompts |
| tools/*.yaml | PostgreSQL prompts: tool.{name} | MCP tool definitions |
| memory/ | PostgreSQL pgvector (episodic) | Seed memories |
| knowledge/ | PostgreSQL pgvector (knowledge) | RAG chunks + embeddings |
| compliance/ | Sentinel policy store | Per-agent policies |
| strategy.py + Dockerfile | Container image (if untrusted) | Custom deterministic logic |
| agents/ | Recursive import | Sub-agent definitions |

### 10.2 GitAgent Export

Running agent → GitAgent directory. Includes updated soul (from production-labeled prompt), accumulated memories, learned corrections. Push to GitHub. Anyone can clone and run the improved agent.

### 10.3 GitHub → Stronghold Prompt Sync

GitHub Action: on push to main → sync prompts to PostgreSQL prompt library with "production" label. On push to staging → "staging" label. ~100 line script (parses YAML frontmatter + markdown, calls Stronghold prompt API).

---

## 11. Package Structure

```
stronghold/
├── protocols/              # Abstract interfaces (the skeleton)
│   ├── router.py, classifier.py, memory.py, tools.py
│   ├── auth.py, skills.py, quota.py, tracing.py, llm.py
│
├── types/                  # Shared value objects + error hierarchy
│   ├── intent.py, model.py, auth.py, skill.py, tool.py
│   ├── memory.py, session.py, config.py, errors.py
│
├── classifier/             # Intent classification engine
│   ├── keyword.py, llm_fallback.py, multi_intent.py
│   ├── complexity.py, engine.py
│
├── router/                 # Model selection (the scoring formula)
│   ├── scorer.py, scarcity.py, speed.py, filter.py, selector.py
│
├── security/               # Warden + Sentinel + Gate
│   ├── warden/             # Threat detection (regex + heuristics + LLM)
│   ├── sentinel/           # LiteLLM guardrail (schema repair, token opt, audit)
│   └── gate.py             # Input processing (sanitize, improve, clarify)
│
├── memory/                 # Memory systems
│   ├── learnings/          # Self-improving corrections
│   ├── episodic/           # 7-tier weighted memories
│   └── scopes.py           # global/team/user/agent/session filtering
│
├── sessions/               # Conversation history
├── quota/                  # Token tracking
│
├── agents/                 # Agent runtime
│   ├── base.py             # Agent class, AgentIdentity, handle()
│   ├── cache.py            # Prompt LRU cache
│   ├── strategies/         # Generic: direct, react, plan_execute, delegate
│   ├── forge/              # Forge agent custom strategy
│   ├── artificer/          # Artificer custom strategy
│   ├── scribe/             # Scribe custom strategy
│   ├── warden_at_arms/     # Warden-at-Arms custom strategy + API discovery
│   ├── registry.py         # Agent CRUD
│   ├── importer.py         # GitAgent import
│   ├── exporter.py         # GitAgent export
│   ├── tournament.py       # Head-to-head scoring + promotion
│   └── intents.py          # Dynamic intent registry
│
├── tools/                  # Tool integration
│   ├── registry.py         # Aggregate MCP + prompt library + legacy tools
│   └── legacy.py           # Wrapper for Conductor tools not yet on MCP
│
├── skills/                 # Skill ecosystem
│   ├── parser.py, loader.py, forge.py, marketplace.py, registry.py
│
├── tracing/                # Observability
│   ├── arize.py, langfuse.py, noop.py, trace.py
│
├── config/                 # Configuration
│   ├── loader.py, defaults.py, env.py
│
├── events.py               # Async EventBus for proactive triggers
├── container.py            # DI container (wires protocols to implementations)
│
└── api/                    # Thin FastAPI transport layer
    ├── app.py              # FastAPI factory
    ├── routes/             # chat.py, models.py, status.py, admin.py, skills.py, agents.py
    └── middleware/          # auth.py, tracing.py
```

---

## 12. What We Build First

### Phase 0: Scaffold
- Repository setup, PostgreSQL schema, file skeleton, agent definitions, dev-tools-mcp server

### Phase 1: Types + Protocols + Auth
- types/ and protocols/ (the contract)
- Auth providers (Keycloak, Entra ID, static key, OpenWebUI headers)
- Config (Pydantic validation, env resolution)
- Test infrastructure (fakes, factories, fixtures)

### Phase 2: Router + Classifier
- router/ (port from Conductor, split into modules)
- classifier/ (port keyword engine + LLM fallback)
- Full test suites (property-based for scoring)

### Phase 3: Security Layer + Security Gate
- security/warden/ (port Bouncer regex patterns, add tool result scanning)
- security/sentinel/ (LiteLLM guardrail — schema validation, repair, token optimization)
- security/gate.py (input processing — sanitize, improve, clarify)

### Phase 4: Memory
- memory/learnings/ (port from Conductor, PostgreSQL, add agent_id + user_id scope)
- memory/episodic/ (port 7-tier system, add scope filtering)
- memory/scopes.py

### Phase 5: Data Layer + Auth
- sessions/ (port, PostgreSQL)
- quota/ (port, PostgreSQL)
- config/ finalized
- Permission table (config-driven RBAC)

### Phase 6: Agent Runtime
- agents/base.py (Agent class, handle(), AgentIdentity)
- agents/strategies/ (direct, react, plan_execute, delegate)
- agents/cache.py (prompt LRU)
- agents/registry.py + intents.py
- events.py (async EventBus)

### Phase 7: Agent Roster + Tools + Security Gate
- Agent definitions (YAML + SOUL.md) for Arbiter, Ranger, Artificer, Scribe, Warden-at-Arms, Forge
- tools/ (LiteLLM MCP gateway integration, legacy wrapper)
- Sentinel registered as LiteLLM guardrail
- Custom strategies for specialists
- Tournament manager (stub) + dynamic intent registry

### Phase 8: Import/Export + API
- agents/importer.py, exporter.py (GitAgent format)
- api/ (thin FastAPI routes)
- GitHub → Stronghold prompt sync action

### Phase 9: Deployment
- Dockerfile, Helm chart, K8s secret manager
- Multi-tenant namespace isolation

### Phase 10: Polish + Ship + Security Gate
- Test coverage audit, performance tests, load tests
- Documentation, README, CHANGELOG, CONTRIBUTING
- v1.0 tag + publish

---

## 13. Source Reference

| Stronghold Module | Conductor Source | Action |
|-------------------|-----------------|--------|
| router/scorer.py | app/router.py:54-226 | Port scoring formula verbatim |
| router/scarcity.py | app/router.py:229-261 | Extract pure function |
| classifier/ | app/classifier.py | Port + split into modules |
| memory/learnings/ | app/learnings.py | Port + PostgreSQL + agent_id scope |
| memory/episodic/ | orchestrator/memory/episodic.py | Port tier system |
| security/warden/ | orchestrator/agents/bouncer.py | Port regex patterns + add tool result scanning |
| agents/base.py | app/main.py:190-698 | Decompose into Agent + strategies |
| tools/legacy.py | app/tools.py | Thin wrapper, migrate to MCP over time |
| sessions/ | app/sessions.py | Port + PostgreSQL |
| quota/ | app/quota.py | Port + PostgreSQL |
| config/ | app/auth.py (permissions only) | Redesign: config-driven RBAC |
| skills/ | app/skills.py, forge.py, skill_hub.py, skill_registry.py | Port + rename |

---

## 14. Threat Model Baseline

See `/root/conductor_security.md` for the full 50-concern threat model of the current Conductor stack. Every concern has a corresponding mitigation in this architecture. The Stronghold security model (Warden + Sentinel + Gate + trust tiers + config-driven RBAC + per-agent memory scoping + K8s secrets) is designed to close every identified gap.

---

## 15. Conductor Feature Migration (CFM-1..CFM-5)

**Added:** 2026-04-18. **Targets:** v1.4 through v1.7 (see `ROADMAP.md`). **Backlog:** `BACKLOG.md` § "Conductor Feature Migration (2026-04-18)".

Five subsystems that port capabilities from the still-running conductor-router with a Stronghold-native shape. They compose: CFM-1 is the foundation (review queue), CFM-2 defines the signal that drives the queue's priorities and gates dispatch (trust floor), CFM-3 provides the declarative-spec artifact whose mutations go through CFM-1, CFM-4 is another artifact kind that flows through CFM-1, and CFM-5 makes all of this observable. Build in order.

### 15.1 CFM-1: Review Queue Engine

**Core insight:** Every forged skill, promoted variant, tier crossing, APM edit, and session-trust descent is the same shape — a decision waiting on a reviewer. One queue with typed items beats N parallel queues because reviewers move through a single inbox, priority policy lives in one place, and the trust signal that drives priority is the same signal everywhere.

The review engine lives **beside** the `OrchestratorEngine`, not inside it. Reviews are human-in-the-loop-often; their latency model (hours/days), failure modes (reviewer unavailability, not exceptions), and scaling needs (independent of request volume) differ fundamentally from execution `WorkItem`s. Mixing them makes priority semantics confusing and starvation math awful.

```
┌──────────────────────────────────────────────────────────────────┐
│                           Reactor (1000Hz)                        │
│  forge.skill_created · variant.hit_threshold · apm.change_submitted │
│  session.stf_descent_pending · learning.ready_for_promote          │
└──────────────────────────────────────────────────────────────────┘
             │ emits                              │ gates
             ▼                                    ▼
┌───────────────────────────┐      ┌───────────────────────────┐
│   Review Queue Engine     │      │   Orchestrator Engine      │
│   (src/stronghold/review) │◀────▶│   (priority WorkItems)     │
│                           │ share│                           │
│   ReviewItem + priority   │types/│   WorkItem + priority     │
│   reducer + classes       │prio  │   reducer                 │
└─────────┬─────────────────┘      └───────────────────────────┘
          │ consumes                           ▲
          ▼                                    │
┌───────────────┬───────────────┐              │
│ Auditor agent │ Human inbox   │              │
│ (ai_allowed,  │ (human_only + │──────────────┘
│ ai_only)      │ override any) │   approvals execute
└───────────────┴───────────────┘
```

**Types.** `ReviewItem { id, kind, subject_ref, origin_stf, origin_user_tier, stakes_tier, submitted_at, reviewer_class, state }`. Kinds: `forge_skill`, `forge_node_kind`, `recipe_variant_promote`, `apm_change`, `user_tier_promote`, `stf_ratchet_decision`, `learning_promote`, `agent_import`.

**Priority calculator.** `f(stakes_impact, −origin_stf, plan_tier_sla, age_bonus, blast_radius, backlog_pressure)` — the queue self-sorts toward "aged + dangerous + high-stakes." Low-trust origins float to the top; high-plan users get SLA priority; domain backlog pressure prevents any single kind from starving.

**Reviewer classes.**
| Class | Who can close | Examples |
|---|---|---|
| `human_only` | Admin with appropriate tier | First T0→T0+ promotion; APM change declaring new tool access; skill forged in Skull session |
| `ai_allowed` | Auditor agent OR human | Recipe variant promotion after N wins; learning promotion after N reinforcements |
| `ai_only` | Auditor only, no human needed | Metrics-driven promotions with hard thresholds — every AI decision still audited and overridable |

The Auditor is the AI reviewer in the existing Herald→QM→Archie→Mason→**Auditor**→Gatekeeper→Master-at-Arms pipeline plan.

**In-session HITL.** STF-ratchet decisions reuse the engine primitives but render inline in the chat UI (synchronous — blocks the turn), because the user is actively present and the session is blocking. Three decision surfaces: (a) pending input would lower STF, (b) action blocked by current STF, (c) passive trust indicator always visible.

**Cross-subsystem boundary.** Review and orchestration share only `types/priority.py` (`PrioritySignal`) and `types/review.py` (`ReviewRequest`). No imports across subsystems.

### 15.2 CFM-2: Session Trust Floor (STF) + Trust Ledger

**Core insight:** Trust is not a fixed property of a user, agent, or tool — it's a *session-scoped minimum* that every contributor can only lower. Once a session is compromised, no amount of subsequent clean activity restores it within that session. This closes the most common prompt-injection path: user pastes innocuous content → tool fetches untrusted doc → doc contains injection → subsequent high-privilege action executes. A monotonically non-increasing STF makes the descent visible and gates the privilege.

**Reducer.**
```
STF(t) = min(
    STF(t-1),                      # never rises
    agent.tier,
    recipe.tier,
    flow_node.kind.tier,
    tool.tier,
    input_source.tier,             # user paste / tool output / retrieved doc / web
    user.trust_score_tier,         # from ledger
    warden.safety_confidence_tier, # from verdict confidence
    ... future contributors
)
```

Every contributor emits `TrustSignal { source, tier, confidence, rationale, trace_ref }` on entry. Unknown sources default to `☠️ Skull`. The session reducer takes `min()`. That's the full arithmetic.

**Monotonicity is a hard invariant.**
- Redaction is cosmetic — removing the poisoned message does not restore STF
- Compaction does not heal — summaries inherit the source's floor (otherwise compaction becomes a laundering vector, a well-known prompt-injection exploit)
- Forks and sub-flows inherit the parent STF
- Only a new session (new trace root) resets — and even then `user.trust_score` persists cross-session

**Read-down, not write-down.** A lowered STF blocks *new* privileged actions, not *reading* already-in-context data. Stricter read-blocking surprises users and adds little real safety (the data's already in the context window; the cognitive model can't un-see it).

**Ledger arithmetic.** User trust points accrue via:
```
Δ trust_points = plan_multiplier × copper_value(action) × session_T_score
```
| Plan | Multiplier |
|---|---:|
| Free | 0 |
| Paid | 1 |
| Team plan | 2 |
| Team admin | 5 |
| Org admin | 10 |
| Super admin | 100 |

| STF at action time | `session_T_score` | Admin override |
|---|---:|---|
| T1 | +2 | — |
| T2 | +1 | — |
| T3 | 0 | — |
| ☠️ Skull | −10 | clamps to 0 for team_admin and above |

Copper is the canonical economic unit — `tokens_used × token_value` — with exchange rates from other currencies via `trust/exchange.py`. Free users have multiplier 0 by design (can't earn, can't sabotage, can't farm). Admins clamp to 0 at Skull to preserve legitimate security testing.

**Tier thresholds.** Exponential, origin-centered slightly positive into T2:
- T2 narrow band (fast honeymoon exit for new paid users)
- T1 and T3 wide (single actions don't cascade; sustained behavior moves tiers)
- T0 and Skull unbounded (gated by badge tiers and soft-barriers respectively)

Thresholds hot-reloadable via `trust/thresholds.yaml`.

**Dispatch gating.** When `STF < recipe.required_tier`, dispatch emits an `stf_insufficient` event (not an exception) and the review engine renders a HITL decision. The user can accept-and-ratchet (explicit consent, logged), reject the blocking input (preserves floor), or quarantine the session.

**Package shape.**
```
src/stronghold/trust/
├── reducer.py         # STF min-reduction over contributors
├── signals.py         # TrustSignal type + source contracts
├── ledger.py          # trust_points accrual, ties into copper ledger
├── thresholds.py      # points → tier contribution; YAML-backed
├── policy.py          # plan_multiplier, admin predicate, skull clamp
└── exchange.py        # copper ↔ other currencies
```

### 15.3 CFM-3: Recipe + Variant Evolution

**Core insight:** Stronghold's tournament-evolution feature (`COMPARISON.md §2`) needs a mechanism that decides *which agent variant wins a route*. The mechanism is Thompson sampling over a Beta posterior per `(recipe_id, variant_id, intent)`. But the artifact being sampled over should be a **pure declarative spec** — executor-agnostic, YAML-serializable, lintable before instantiation. This forces spec/engine separation and makes a single envelope work for both simple strategy agents and graph/workflow agents.

**Single envelope, one pattern.**

```python
class RecipeSpec:                    # pure data, no Python callables
    id: str
    agent_ref: str
    model_class: str                 # symbolic — router resolves at dispatch
    tools: list[ToolRef]             # names only, no handlers
    memory: MemoryPolicy
    apm_ref: str | None
    required_tier: TrustTier
    flow: FlowSpec                   # always a graph

class FlowSpec:
    entry: NodeRef
    state: StateSchema
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]

class NodeSpec:
    id: str
    kind: str                        # "reason" | "tool" | "branch" | "recipe" | "collect" | third-party
    params: dict                     # schema-validated per-kind
    # no executor, no import paths
```

A simple strategy agent is a degenerate graph: one `reason` node, no edges. A graph/workflow agent uses multiple nodes and conditional edges. Same envelope, same validator, same variants, same promotion logic. Nesting falls out naturally — a `recipe` node references another RecipeSpec by id, which is how Archie→Mason-style pipelines compose.

**Spec vs engine.**
- `src/stronghold/evaluation/` owns specs: `recipes.py` (CRUD), `thompson.py` (sampling), `outcomes.py`, `promotion.py`, `validator.py` (reachability, schema check, no-orphan edges, no-undeclared-state-refs)
- `src/stronghold/execution/` owns interpretation: `graph_runner.py`, `node_handlers.py`, `state.py`
- They share only `types/recipe.py`. Multiple executors can interpret the same spec — today's tool-loop, tomorrow's streaming executor, a replay engine for RCA.

**Open node-kind registry with Skull default.** `NodeSpec.kind` is open, not a closed enum. Built-in kinds (`reason`, `tool`, `branch`, `recipe`, `collect`) are reserved and ship at T0. Third-party or Forge-created kinds register at runtime with a required `param_schema` and `declared_side_effects: list[str]`. **Unknown or unregistered kinds default to `☠️ Skull`** — declarative specs referencing them are harmless (a spec is just data), only execution is gated. This reuses the existing trust-tier machinery instead of inventing a parallel governance mechanism.

Tier resolution: `effective_tier = min(recipe.tier, min(node.kind.tier for node in flow.nodes))`. `declared_side_effects` are enforced by Sentinel at run time — a kind declaring `["network"]` that tries to open a filesystem handle gets killed mid-span. Prevents tier-promotion by misdirection.

**Thompson sampling.** For each dispatch, sample from `Beta(successes, failures)` per `(recipe_id, variant_id, intent)`. Higher posterior = more likely to be chosen. Outcomes update the posterior after each `WorkItem` completion. Variants accumulate evidence; Thompson's regret bounds keep exploration sensible.

**Promotion via review queue.** `promote_variant` does not execute inline. A reactor trigger enqueues a `recipe_variant_promote` review when a variant hits policy thresholds (e.g., 20 wins + 5× advantage over incumbent). Review engine (CFM-1) handles the decision — often `ai_allowed` with human override.

**GitAgent round-trip.** `RecipeSpec` serializes cleanly to YAML; `variants` live alongside the parent spec. Export and re-import round-trip — no Python objects, no import paths, no fragile pickle. This is what makes recipes shareable and makes the "GitAgent marketplace" in COMPARISON a real story.

### 15.4 CFM-4: APM (Agent Personality Manifest)

**Core insight:** Today `AgentIdentity` is config scaffolding — there's no human-readable, editable, round-trippable personality artifact. APM gives each agent a structured 7-section personality document that any reasoning strategy can render into a system-prompt fragment. This is what makes GitAgent export-import complete.

**Schema.**
```python
class APM:
    identity: str            # who the agent is
    core_values: list[str]
    communication_style: str
    expertise: list[str]
    boundaries: list[str]    # what it refuses or escalates
    tools_and_methods: str
    memory_anchors: list[str]  # canonical memories the agent always carries
```

Every agent resolves exactly one APM at load. If the agent declares none, a trust-tier baseline is merged in (T0 agents get the "canonical built-in" APM; T3 agents get the "community-provided default" APM, etc.).

**Warden-gated writes.** `PUT /v1/stronghold/agents/{id}/apm` goes through Warden scan before persistence — an APM is an agent prompt, which is one of the highest-trust surfaces in the system. APM changes enqueue a `apm_change` review (human_only by default; policy may downgrade to ai_allowed after operational maturity).

**Rendering is strategy-agnostic.** `prompts/apm_renderer.py` turns an APM into a system-prompt fragment. Every reasoning strategy (direct, react, plan_execute, delegate, custom) calls the renderer. No strategy-specific wiring means graph-based agents (CFM-3) and strategy-based agents share the same APM plumbing.

**Audit.** Every change writes an audit entry: `actor`, `old_hash`, `new_hash`, `trace_id`. The hash-on-save is how Intel's evolution timeline (CFM-5) renders APM diffs.

### 15.5 CFM-5: Intel Dashboard

**Core insight:** The memory, learning, and mutation subsystems accumulate enormous amounts of signal, but today that signal is opaque — there's no place to see what's been happening. Intel exposes Langfuse traces, RCA post-mortems, an evolution timeline across all mutation sources, and the review queue inbox as a single four-tab dashboard. It turns Stronghold's existing stores from write-only into reviewable.

**Four tabs.**

| Tab | Source | What it shows |
|---|---|---|
| **Traces** | Langfuse | Paginated browse, filter by agent/intent/verdict, click into full span tree, inline scoring (1–5 + tags + free-text note) |
| **RCA** | `rca.py` (auto-generated post-mortems from failed `WorkItem`s) | Root cause, failing tool, suggested learning, retrigger button |
| **Evolution** | Aggregator across memory, recipes, skills, learnings, node kinds | Chronological `EvolutionEvent` stream with structural diffs (RecipeSpec, FlowSpec, node graph changes — not just prompt text) |
| **Reviews** | Review Queue Engine (CFM-1) | Same inbox as `/dashboard/reviews.html`, reproduced here for workflow continuity |

**Trace scoring is a trust event.** `POST /v1/stronghold/traces/{id}/score` dual-writes to Langfuse and to the outcomes store. The scorer earns trust points via the ledger (CFM-2) — thoughtful reviewing is positive behavior in the trust economy. Rubber-stamping flagged by pattern detection over the ledger.

**RCA pipeline.** A `WorkItem` failure emits a reactor event → bounded-concurrency `rca.generate_rca` runs → structured post-mortem lands in the RCA store → at low weight, fed to `memory/learnings/extractor.py` as a candidate learning. Promotion requires reinforcement from other signals (recurring failure, operator confirmation, matching fail→succeed pattern). This turns failure into memory without turning every failure into a false positive.

**Structural diff rendering.** Because RecipeSpec and FlowSpec are declarative YAML (CFM-3), the evolution tab can render *structural* diffs — "variant v2 added a `branch` node at position 3 and retargeted edge e4 to the new branch" — not just "the prompt changed." This is dramatically more useful for reviewing what the system is actually learning about itself.

### 15.6 Reactor Enhancements (land with CFM-1)

Two small additions to the existing reactor that complement the review queue:

**Density-aware jitter.** Per-firing-bin trigger count drives jitter budget: `max_jitter_secs = min(ceiling, base + k × log2(density))`. A single trigger at 06:00 fires exactly on time (density=1 → log=0 → base jitter). A thousand triggers at 06:00 spread into a minutes-wide window. Prevents thundering-herd on shared firing times.

**Coalescence / timer-slack.** A trigger can declare a tolerance window: `leeway: "±Nmin"`. The reactor looks for other triggers within overlapping leeway and snaps them to a shared firing time — batch DB writes, reuse warm caches, single Langfuse flush. Opposite direction from density jitter: spread when dense, gather when sparse.

Combined: the reactor becomes a *load-aware scheduler*. Trigger authors declare how much they care (leeway); the reactor decides where inside that window to fire based on what else is happening. Extend `TriggerSpec` to accept `jitter` for `TIME` mode (currently only `INTERVAL`) and add the `leeway` field. Log bucketing decisions in the trigger audit so "why did this fire at 06:07?" is answerable.

### 15.7 Build Order

CFM-1 is the foundation — every promotion and review in CFM-2..CFM-5 consumes it. CFM-2 gates dispatch for the rest. CFM-3 and CFM-4 are independent and can land in parallel after CFM-2. CFM-5 lands last because its evolution timeline wants to include recipe and APM changes.

Recommended sequence: **CFM-1 → CFM-2 → (CFM-3 || CFM-4) → CFM-5**. Reactor enhancements (§15.6) ride alongside CFM-1. Gamification, skull soft-barrier engine, and currency exchange UX (v1.7) follow CFM-2 once the trust economy has data to surface.

---

## 16. CI Gates (Code-Quality Gates)

**Added:** 2026-04-29. **Scope:** the eight CI quality gates that run on every PR. Owns the policy ("what we measure"), the enforcement model ("how we transition from warn to block"), and the contracts ("how each gate is wired"). The runtime wiring lives in `.github/workflows/ci.yml`; this section is the source of truth for *why* each step exists and *what* shape it must take.

### 16.1 Goals & Non-Goals

**Goals.**
1. **Catch regressions, not legacy debt.** A PR that doesn't make a metric worse must not be blocked by a metric that was already bad on its base. Baseline-freeze is the load-bearing primitive — every gate either ratchets a numeric threshold or carries an explicit allow-list of pre-existing offenders.
2. **Fast PR feedback.** The pattern-level gates (Xenon, Vulture, duplication, docstring, assertion-pattern lint) finish inside 60s on a clean checkout. The semantic gates (mutation, LLM judge) are tier-3-only — PR-to-`integration`/`main` — because their wall-time and dollar cost don't fit a per-push budget.
3. **Single rollout shape per gate.** Every gate moves through the same three states: `disabled → warn-only → blocking`. No gate is born blocking. Promotion happens by deleting `|| true` from one workflow step, not by editing prose.
4. **One source of truth per metric.** Thresholds, baseline files, and exclusion lists live next to the code they describe (`.xenon-baseline.json`, `.vulture_whitelist.py`, `.jscpd.json`, `pyproject.toml [tool.interrogate]`). The workflow file consumes them; it never embeds the numbers.

**Non-goals.**
- Replacing the existing tiered pytest gates (Tier-1/2/3 in `ci.yml`). Coverage and test count are orthogonal to the quality dimensions §16 covers.
- Catching every code smell. The `docs/code-smell-catalog-2026-04-23.md` catalog is the *full* taxonomy; §16 picks the subset that has a cheap-and-deterministic detector. Smells without one stay manual-review territory.
- Replacing Auditor's existing rubric (presence + pytest-green + ruff/mypy/bandit). §16 sits *after* Auditor in the pipeline and adds the dimensions Auditor doesn't measure (cf. §16.4.5–7 and `docs/test-quality-audit-and-ci-gate-proposal.md` §4).

### 16.2 Gate Inventory

Eight gates organized by *what they catch* and *when they run*. The first column is the canonical gate ID used in commit messages, baseline filenames, and ratchet log entries.

| ID  | Gate | Catches | Tool | Tier | Initial state | Eventual state |
|-----|------|---------|------|------|---------------|----------------|
| G-1 | **Complexity** | Functions/modules above rank C cyclomatic complexity. | `xenon` (radon) | T1 — every PR | warn-only (today: `\|\| true`) | blocking, `--max-absolute B` |
| G-2 | **Dead code** | Unused functions, classes, attributes, imports not in `.vulture_whitelist.py`. | `vulture` | T1 | blocking (today) | blocking + monotonically-shrinking-whitelist enforcement |
| G-3 | **Duplication** | Copy-pasted blocks ≥ 50 tokens / 10 lines across `src/stronghold/`. | `jscpd` | T1 | disabled (new) | blocking, ≤5% codebase ratchet to ≤2% |
| G-4 | **Docstring coverage** | Public functions/classes missing docstrings. | `interrogate` | T1 | disabled (new) | blocking, fail-under set to current floor, ratchet +5pp/quarter |
| G-5 | **Assertion-pattern lint** | Test smells with deterministic detectors: tolerant status tuples, post-construct `isinstance`, sole-`is not None`, no-assert tests, internal-module `@patch`. | custom AST walker (`scripts/check_assertion_patterns.py`) | T1, scope = changed test files | disabled (new) | blocking on net-new violations vs. baseline |
| G-6 | **Mutation strength** | Tautological tests on changed src files (mutation score < threshold). | `mutmut` (or `cosmic-ray`) | T3 — PR to `integration`/`main` only | disabled (new) | warn-only → blocking when ≥60% on changed files for 4 consecutive weeks |
| G-7 | **LLM assertion judge** | Semantic test smells pattern-lint can't see (BDD-mismatch, AC-wording duplication). | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) classifier | T3 | disabled (new) | block on `BAD`, comment-only on `WEAK` |
| G-8 | **Quality-baseline freeze** | Cross-cutting: enforces "PR may not regress G-1..G-7 baselines". | `scripts/check_quality_baselines.py` (orchestrator) | T1 | warn-only | blocking once G-1..G-5 are individually blocking |

**Tier semantics.**
- **T1** — runs on `push` to working branches and on every PR. Must finish inside the lint job's wall-time budget (currently ~3 min total).
- **T3** — runs only when `github.base_ref` is `integration` or `main`. Mirrors the existing `Tier 3: Full test suite + 90% coverage` step gating.

**Why eight, not three.** The `docs/test-quality-audit-and-ci-gate-proposal.md` §3-4 design proposes Pattern (A) + Mutation (B) + LLM (C) as the *test-quality* gates. §16 keeps all three (G-5/G-6/G-7) and adds four production-code gates (G-1/G-2/G-3/G-4) plus the cross-cutting baseline-freeze (G-8). Test quality and production-code quality are independent regression vectors — a PR can fail G-3 (dup) without touching tests, and fail G-7 (judge) without touching `src/`.

### 16.3 Enforcement Model — Baseline-Freeze, then Ratchet

Every gate uses the same two-phase model. The phases are deliberate; skipping straight to "blocking with a hard threshold" is what produced the `|| true` patches we already carry on G-1 (Xenon) and `pip-audit`.

#### 16.3.1 Phase 1 — Baseline-Freeze

**Capture the current state of the metric. Block only on regressions against that snapshot.**

The baseline file format is gate-specific (see §16.7) but the *contract* is identical:

1. **Snapshot is checked in.** The baseline lives in the repo, not in a CI artifact store. A reviewer can diff it. CI is reproducible without external state.
2. **Snapshot is regenerated by a documented command.** Each gate ships a `make baseline-<gate>` target. The command is the only sanctioned way to write the baseline file; PRs that hand-edit it must justify the change in the commit body.
3. **Comparison is exact, not statistical.** The gate fails if the PR introduces a violation *not present* in the baseline. It does not pass-on-average. A baseline of `["agents/base.py rank D"]` does not let a new file appear at rank D — it lets exactly that file remain at rank D.
4. **Removing baselined offenders does not reward the PR.** Shrinking the baseline is encouraged but not required for merge. A PR that fixes a baselined file regenerates the snapshot and commits the smaller file as part of its diff.

This is the regime CLAUDE.md Build Rule #1 ("No Code Without Architecture") and the test-quality audit (§4) implicitly assume: the baseline is the architectural artifact, the gate is its enforcement.

#### 16.3.2 Phase 2 — Ratchet

**Once a gate is blocking on net-new violations, tighten the threshold on a documented cadence so the baseline is forced to shrink.**

Two ratchet shapes:

- **Numeric ratchet** (G-1, G-3, G-4, G-6) — a single threshold number tightens on a schedule. Example: G-1 Xenon goes `--max-absolute C` (today) → `B` (Q+1) → `B` with `--max-modules B` (Q+2). The ratchet schedule is committed alongside the threshold (`pyproject.toml` for interrogate; a comment block in `ci.yml` for xenon).
- **Set ratchet** (G-2, G-5, G-7) — a set of permitted offenders shrinks on a schedule. Example: G-2 Vulture's `.vulture_whitelist.py` is **monotonically non-growing** between scheduled grow events. PRs that need to add an entry must apply the `vulture-whitelist-grow` label and link a justification in the PR body.

**Ratchet cadence.** Default is one tick per quarter, gated on:
- All currently-blocking gates green for 4 consecutive weeks on `integration`.
- No emergency-revert of a previous ratchet in the prior 30 days.

A ratchet that's reverted within 30 days resets the cadence and triggers a §16.10-style open-question entry for review.

#### 16.3.3 The Anti-Pattern this Replaces

Today's `ci.yml` carries `xenon ... || true` and `pip-audit ... || true`. Both are warn-only by accident, not by design — the suppression has no associated baseline, no ratchet, and no exit criterion. The §16.3 model formalizes the warn-only state into Phase 1 and gives it a path out. Phase-1 gates that sit in `|| true` for more than two quarters without a ratchet plan are flagged in §16.10 as decision-debt.

### 16.4 Per-Gate Specifications

Each subsection follows the same shape: **Purpose**, **Tool & invocation**, **Baseline shape**, **Ratchet plan**, **Exit code contract**.

#### 16.4.1 G-1 Complexity (Xenon)

**Purpose.** Block PRs that introduce new high-complexity blocks. Cyclomatic complexity ≥ rank D is a known correlate of defect density and a friction tax on every reviewer.

**Tool & invocation.**
```
xenon --max-absolute <ABS> --max-modules <MOD> --max-average <AVG> \
      --exclude-from .xenon-baseline.json src/stronghold/
```
The `--exclude-from` flag is *not* a stock Xenon feature; G-1 ships a wrapper (`scripts/xenon_with_baseline.py`) that reads the baseline JSON, runs Xenon over `src/stronghold/`, and post-filters the violations to net-new entries. Stock Xenon's behaviour ("fail any block above rank") is the wrong mode for §16.3.1.

**Baseline shape.** `.xenon-baseline.json`:
```json
{
  "generated_at": "2026-04-29T00:00:00Z",
  "command": "make baseline-xenon",
  "thresholds": {"absolute": "C", "modules": "C", "average": "C"},
  "permitted_above_threshold": [
    {"file": "src/stronghold/skills/fixer.py", "block": "FixerStrategy.fix", "rank": "E"},
    {"file": "src/stronghold/agents/base.py", "block": "Agent.handle", "rank": "D"},
    {"file": "src/stronghold/api/routes/admin.py", "block": "module", "rank": "D"}
  ]
}
```

**Ratchet plan.**
- Q2 2026: capture baseline, drop `|| true`, threshold `C/C/C`.
- Q3 2026: tighten to `B` for any block *not* in baseline (baseline still tolerated).
- Q4 2026: shrink baseline by ≥ 30%, target `B` codebase-wide.
- Q1 2027: zero-baseline `B/B/B`. Exit Phase 1.

**Exit code.** `0` if no net-new offenders; `1` otherwise. `2` reserved for tool errors (Xenon crash, malformed baseline).

#### 16.4.2 G-2 Dead Code (Vulture)

**Purpose.** Block PRs that introduce unused functions/classes/imports/attributes. Already blocking today via `.vulture_whitelist.py`. §16.4.2 formalizes the **whitelist-shrink-only** policy.

**Tool & invocation.** Unchanged from current `ci.yml`:
```
vulture src/stronghold/ .vulture_whitelist.py --min-confidence 100
```

**Baseline shape.** `.vulture_whitelist.py` (already extant). The header explains the regeneration command and the framework-indirection rationale. **New rule (§16):** every entry must carry an inline `# unused <kind> (<path>:<line>)` annotation (already enforced by `vulture --make-whitelist` output).

**Whitelist-grow protocol.**
- Default: a PR's diff against `.vulture_whitelist.py` must be **empty or a strict subset**. CI computes `diff(base, head)` over the whitelist and fails if any line was added.
- Override: `vulture-whitelist-grow` PR label suspends the strict-subset check for that PR. The label is restricted to operator-tier reviewers in branch protection. Each grow event must (a) link the framework or DI-binding that justifies the entry and (b) appear in the PR body under a `## Whitelist additions` heading.

**Ratchet plan.** No threshold ratchet (Vulture is binary). Cadence ratchet: monthly review of whitelist entries; entries whose justification has gone stale (e.g., framework migrated away) are deleted. Target: −10% entries per quarter.

**Exit code.** `0` clean; `1` net-new dead code (including unauthorized whitelist growth); `2` tool error.

#### 16.4.3 G-3 Duplication (jscpd)

**Purpose.** Block PRs that copy-paste blocks ≥ 50 tokens / 10 lines across the codebase. Duplicate code is the #1 detected smell in `docs/code-smell-catalog-2026-04-23.md` and the cheapest to detect deterministically.

**Tool & invocation.**
```
npx jscpd@4 --config .jscpd.json src/stronghold/
```
Node tooling acceptable here because (a) it's PR-time-only, not runtime; (b) jscpd is the most mature multi-language clone detector; (c) Python-native alternatives (`pylint --enable=duplicate-code`) are noisier and slower.

**Baseline shape.** `.jscpd.json` config + `.jscpd-baseline.json` snapshot:
```json
{
  "generated_at": "2026-04-29T00:00:00Z",
  "duplication_pct": 2.4,
  "tolerated_clones": [
    {"a": "src/stronghold/api/routes/admin.py:120-140", "b": "src/stronghold/api/routes/dashboard.py:88-108", "tokens": 73}
  ]
}
```

**Ratchet plan.**
- Phase 1 launch: capture baseline `duplication_pct` (estimate ≤ 5%); fail PRs that *increase* the pct or add new clone pairs.
- Q+1: ratchet target to `floor(current) − 0.5pp`.
- Q+2 onwards: −0.5pp per quarter until 1.0%.

**Exit code.** `0` no net-new duplication; `1` net-new clones or pct above ceiling; `2` tool error.

#### 16.4.4 G-4 Docstring Coverage (interrogate)

**Purpose.** Block PRs that add public APIs without docstrings. Stronghold's protocol-driven DI (CLAUDE.md "Protocol-Driven DI") only works if the protocol surface is self-describing.

**Tool & invocation.**
```
interrogate -c pyproject.toml src/stronghold/
```

**Config (`pyproject.toml [tool.interrogate]`).**
```toml
[tool.interrogate]
fail-under = <FLOOR>           # captured at baseline freeze
ignore-init-module = true
ignore-init-method = true
ignore-magic = true
ignore-private = true
ignore-property-decorators = true
exclude = ["tests", "migrations", "src/stronghold/types", "src/stronghold/protocols"]
```

**Why exclude `types/` and `protocols/`.** Dataclasses in `types/` document themselves via field names + types. Protocol stubs in `protocols/` carry module-level docstrings on the protocol class; per-method `...` bodies don't need their own docstring. Including them inflates the metric without improving discoverability.

**Ratchet plan.**
- Phase 1: measure today's coverage, set `fail-under` to `floor(current)`.
- +5pp per quarter until 80%.
- Floor never decreases. A PR that lowers coverage but stays above `fail-under` still warns in the PR comment.

**Exit code.** Interrogate's native: `0` ≥ `fail-under`; `1` below; `2` tool error.

#### 16.4.5 G-5 Assertion-Pattern Lint (Option A)

**Purpose.** Catch the deterministic test smells from `docs/test-quality-audit-and-ci-gate-proposal.md` §3 Gate A. These are the patterns that produced 60-90% of Mason's WEAK/BAD tests pre-Wave-2B.

**Detector. `scripts/check_assertion_patterns.py`** — AST walker that flags:
1. `status_code in (...)` with len(tuple) > 1 — over-tolerant status assertion.
2. `assert isinstance(x, T)` where `x` is the LHS of `x = T(...)` in the same function body — post-construct tautology.
3. `assert hasattr(obj, "name")` not inside a `pytest.raises` block — trivial-type assertion.
4. `def test_*` whose body has zero `assert` / `pytest.raises` / `await` of an expectation helper — no-assert test.
5. `@patch("stronghold.<...>")` — patching internal modules instead of using `tests/fakes.py`.
6. Sole assertion in body is `assert <name> is not None` — minimal-info assertion.

**Tool & invocation.**
```
python scripts/check_assertion_patterns.py \
       --baseline .assertion-pattern-baseline.json \
       $(git diff --name-only --diff-filter=ACMR "$BASE" -- 'tests/**/*.py')
```
Scope is **changed test files only** — full-suite run is reserved for `make baseline-assertions`.

**Baseline shape.** `.assertion-pattern-baseline.json` keyed by `(file, function, smell-id)`:
```json
{
  "generated_at": "2026-04-29T00:00:00Z",
  "permitted": [
    {"file": "tests/foo/test_x.py", "function": "test_legacy_route", "smell": "TOLERANT_STATUS", "reason": "pre-audit"}
  ]
}
```

**Ratchet plan.** Set ratchet — baseline shrinks only.
- Phase 1: snapshot today's offenders (target ≤ 50 entries; the audit closed most).
- Q+1: shrink baseline by 50%.
- Q+2: empty baseline; gate is unconditional.

**Exit code.** `0` no net-new smells in changed tests; `1` net-new smells; `2` baseline malformed or script error.

#### 16.4.6 G-6 Mutation Strength (Option B)

**Purpose.** Catch tautologies pattern-lint can't see. A test that reverts a logic operator and still passes is the load-bearing failure mode (cf. §3 audit, B14/B16/B17).

**Tool & invocation.** Tier-3 only (PR to `integration`/`main`):
```
mutmut run --paths-to-mutate=$CHANGED_SRC_FILES \
           --runner='pytest -x --no-cov -q' \
           --use-coverage
mutmut results --json > .mutation-report.json
scripts/check_mutation_score.py --threshold 0.60 \
       --baseline .mutation-baseline.json .mutation-report.json
```
`$CHANGED_SRC_FILES` = `git diff --name-only ... -- 'src/stronghold/**/*.py'`. Wall-time cap **5 minutes**; if exceeded, gate emits a warn-only check and posts a PR comment listing un-mutated files. Wall-time exceedance is *not* a fail in Phase 1 — non-determinism in async paths and mutmut's known cost on large codebases makes a hard cap a flake source.

**Baseline shape.** `.mutation-baseline.json`:
```json
{
  "generated_at": "2026-04-29T00:00:00Z",
  "per_file_score": {
    "src/stronghold/router/selector.py": 0.71,
    "src/stronghold/security/warden/regex.py": 0.83
  }
}
```

**Pass condition.** For each changed file `f`:
- If `f` in baseline: PR's score(`f`) ≥ baseline(`f`) − 5pp tolerance.
- If `f` not in baseline (new file): PR's score(`f`) ≥ 60%.

**Ratchet plan.**
- Phase 1: warn-only for 4 weeks; collect drift data on async modules.
- Phase 2: blocking with the per-file rule above.
- Q+1 onwards: tolerance shrinks 1pp/quarter; absolute floor rises 5pp/quarter to 75%.

**Exit code.** `0` pass; `1` block (Phase 2+); `2` tool error or wall-time exceedance (Phase 1: `0`).

#### 16.4.7 G-7 LLM Assertion Judge (Option C)

**Purpose.** Catch semantic test smells pattern-lint and mutation can't see — BDD-comment-mismatch, AC-wording duplication, status-tolerance dressed as multiple assertions. Per the audit §0, the *primary fix* is spec-driven test authoring; G-7 is the safety net for code paths that skip the spec step.

**Tool & invocation.** GitHub Action job (`.github/workflows/ci.yml` new job `assertion-judge`, T3 only):
```
python scripts/run_assertion_judge.py \
       --model claude-haiku-4-5-20251001 \
       --temperature 0 \
       --golden-set tests/specs/assertion-judge-golden.jsonl \
       --pr-files $(gh pr diff --name-only --files-only) \
       --max-cost-usd 0.10 \
       --output .judge-report.json
```

**Determinism guards.**
- Model pinned to a dated snapshot (`claude-haiku-4-5-20251001`). Updates land via PR + golden-set regression.
- `temperature=0`, fixed system prompt checked in at `prompts/assertion_judge_v1.md`.
- Few-shot seeded from the master catalog (`docs/test-audit-2026-04-17.csv`).

**Pass condition.**
- Any `BAD` verdict in changed tests → block.
- Any `WEAK` verdict → bot comment with the judge's reasoning, not a block, unless the file is also in the §16.4.5 baseline (compounding signal).
- All `GOOD` → green check.

**Cost guard.** Hard cap `$0.10/PR` enforced by `--max-cost-usd`. Exceedance emits a warn-only check; gate does not block on cost overruns (drives reviewers toward smaller test diffs without weaponizing the gate).

**Baseline shape.** No persistent baseline (per-PR judgement). Golden set lives at `tests/specs/assertion-judge-golden.jsonl` — held-out examples whose expected verdicts pin the judge's calibration. CI runs the judge over the golden set on judge-prompt or model changes; >2% verdict drift blocks the prompt-change PR.

**Ratchet plan.**
- Phase 1 (warn-only, 4 weeks): collect verdicts, hand-audit 50 random PRs to validate calibration.
- Phase 2: block on `BAD`.
- Phase 3 (Q+2): block on `WEAK` if file is in §16.4.5 baseline.

**Exit code.** `0` pass; `1` block; `2` cost-cap exceeded or model unreachable (Phase 1: `0`).

#### 16.4.8 G-8 Quality-Baseline Freeze (cross-cutting)

**Purpose.** Guarantee that no individual gate's baseline file is silently widened. G-8 reads the per-gate baseline files in the PR diff and fails if any grew without an authorizing label.

**Tool & invocation.** `scripts/check_quality_baselines.py`:
```
python scripts/check_quality_baselines.py \
       --base "$BASE" --head HEAD \
       --label-allow-grow vulture-whitelist-grow,xenon-baseline-grow,jscpd-baseline-grow
```

**Pass condition.** For each baseline file in `[
  .xenon-baseline.json,
  .vulture_whitelist.py,
  .jscpd-baseline.json,
  .assertion-pattern-baseline.json,
  .mutation-baseline.json,
  pyproject.toml::tool.interrogate.fail-under (numeric: must not decrease)
]`:
- New entries added → fail unless the corresponding `*-grow` label is on the PR.
- Removed entries → always pass (shrinking is the goal).
- For numeric thresholds: PR may *raise* `fail-under`/scores; lowering requires the corresponding grow label.

**Why a separate gate.** The individual gates (G-1..G-7) compare PR-state against their own baseline. G-8 compares the baseline file *itself* between base and head. Without G-8, a PR could lower G-4's `fail-under` from 65 to 50 to dodge the gate; G-1..G-7 wouldn't notice because their threshold reads the post-edit value.

**Exit code.** `0` no unauthorized growth; `1` unauthorized growth; `2` script error.

### 16.5 Acceptance Criteria (Gherkin)

The criteria below are the testable contract for the §16 implementation. They are written in the form §16's *test stubs* will take, so a TDD-first land (CLAUDE.md Build Rule #2) can begin from this list directly.

#### 16.5.1 G-1 Complexity

```gherkin
Feature: G-1 Xenon complexity gate
  Scenario: PR adds a new rank-D function in a clean file
    Given .xenon-baseline.json contains no entry for src/stronghold/foo/bar.py
    And  the PR adds a function `bar.complicated_thing` with rank D
    When the lint job runs
    Then scripts/xenon_with_baseline.py exits 1
    And  the failure message names the new offender and points at .xenon-baseline.json

  Scenario: PR refactors a baselined rank-D function to rank-B
    Given .xenon-baseline.json contains {file: "agents/base.py", block: "Agent.handle", rank: "D"}
    And  the PR drops Agent.handle to rank B
    When the lint job runs
    Then scripts/xenon_with_baseline.py exits 0
    And  the PR diff includes the baseline entry's removal

  Scenario: PR raises an existing rank-D function to rank-E
    Given .xenon-baseline.json contains {file: "agents/base.py", block: "Agent.handle", rank: "D"}
    And  the PR pushes Agent.handle to rank E
    When the lint job runs
    Then scripts/xenon_with_baseline.py exits 1
    And  the failure message says "regression: Agent.handle was D, now E"
```

#### 16.5.2 G-2 Vulture

```gherkin
Feature: G-2 Vulture dead-code gate
  Scenario: PR adds a new unused function
    Given the function did not exist on base
    And  the PR has no `vulture-whitelist-grow` label
    When the lint job runs
    Then vulture exits 1
    And  the report lists the new symbol

  Scenario: PR adds a framework-mediated method to .vulture_whitelist.py
    Given the PR has the `vulture-whitelist-grow` label
    And  the PR body contains a `## Whitelist additions` heading with the new entry
    When the lint job runs
    Then vulture exits 0
    And  the G-8 baseline-freeze gate also passes

  Scenario: PR adds an entry to .vulture_whitelist.py without the grow label
    Given the PR has no `vulture-whitelist-grow` label
    When the lint job runs
    Then G-8 baseline-freeze exits 1
    And  the failure message names .vulture_whitelist.py and the offending diff lines
```

#### 16.5.3 G-3 Duplication

```gherkin
Feature: G-3 jscpd duplication gate
  Scenario: PR introduces a new ≥50-token clone
    Given baseline duplication_pct = 2.4
    And  the PR copies a 60-token block from routes/admin.py to routes/dashboard.py
    When the lint job runs
    Then jscpd exits 1
    And  the report shows the source/dest pair

  Scenario: PR removes a baselined clone pair
    Given .jscpd-baseline.json contains a clone pair (admin.py, dashboard.py)
    And  the PR refactors both to call a shared helper
    When the lint job runs
    Then jscpd exits 0
    And  the new baseline file is committed in the PR with the pair removed
```

#### 16.5.4 G-4 Docstring coverage

```gherkin
Feature: G-4 Interrogate docstring gate
  Scenario: PR adds a public function with a docstring
    Given current coverage = 62%
    And  pyproject.toml fail-under = 60
    And  the new function has a docstring
    When the lint job runs
    Then interrogate exits 0

  Scenario: PR adds a public function with no docstring, dropping coverage below floor
    Given current coverage = 60.2%
    And  pyproject.toml fail-under = 60
    And  the new function has no docstring, dropping coverage to 59.8%
    When the lint job runs
    Then interrogate exits 1
    And  the report names the missing-docstring file:line

  Scenario: PR adds a Protocol method stub with no docstring
    Given the new method lives under src/stronghold/protocols/
    When the lint job runs
    Then interrogate exits 0
    And  the file is excluded by pyproject [tool.interrogate].exclude
```

#### 16.5.5 G-5 Assertion-pattern lint

```gherkin
Feature: G-5 assertion-pattern AST gate
  Scenario: PR adds a new test using `status_code in (200, 401)`
    Given .assertion-pattern-baseline.json has no entry for the new test
    When the lint job runs
    Then scripts/check_assertion_patterns.py exits 1
    And  the report names the file:line and smell-id TOLERANT_STATUS

  Scenario: PR modifies a baselined test to a different smell
    Given .assertion-pattern-baseline.json has {test_legacy_route: TOLERANT_STATUS}
    And  the PR rewrites the test to use `assert hasattr(...)` instead
    When the lint job runs
    Then scripts/check_assertion_patterns.py exits 1
    And  the failure message says "smell changed: TOLERANT_STATUS → TRIVIAL_HASATTR; baseline grants TOLERANT_STATUS only"

  Scenario: PR removes a baselined test entirely
    Given .assertion-pattern-baseline.json has {test_legacy_route: TOLERANT_STATUS}
    And  the PR deletes test_legacy_route
    When the lint job runs
    Then scripts/check_assertion_patterns.py exits 0
    And  the new baseline has the entry removed
```

#### 16.5.6 G-6 Mutation strength

```gherkin
Feature: G-6 mutation strength gate (T3)
  Scenario: PR adds a tautological test
    Given .mutation-baseline.json: {router/selector.py: 0.71}
    And  the PR adds a test that always passes regardless of selector logic
    When the test job runs against integration
    Then mutmut for router/selector.py reports score < 0.66 (0.71 − 5pp)
    And  scripts/check_mutation_score.py exits 1

  Scenario: PR creates a new file with weak tests
    Given the new file is not in .mutation-baseline.json
    And  the new file's mutation score = 0.45
    When the test job runs against integration
    Then scripts/check_mutation_score.py exits 1 (below 60% floor for new files)

  Scenario: mutmut wall-time exceeds 5 minutes (Phase 1)
    Given mutmut is in Phase 1 (warn-only)
    When wall-time exceeds 300s
    Then the gate posts a warn comment
    And  the gate exits 0
```

#### 16.5.7 G-7 LLM judge

```gherkin
Feature: G-7 LLM assertion judge (T3)
  Scenario: PR adds a test the judge classifies BAD
    Given the judge is in Phase 2 (blocking on BAD)
    And  the new test is classified BAD with reasoning "BDD comment says 'rejects', body asserts 200"
    When the assertion-judge job runs
    Then it exits 1
    And  a PR comment is posted with the classification + reasoning

  Scenario: judge classifies WEAK on a file in §16.4.5 baseline
    Given the judge is in Phase 3
    And  the test file is in .assertion-pattern-baseline.json
    And  the new test is classified WEAK
    When the assertion-judge job runs
    Then it exits 1 (compounding signal)

  Scenario: cost cap exceeded
    Given --max-cost-usd 0.10
    When cost mid-run reaches $0.11
    Then the script aborts pending classifications
    And  it posts a warn comment and exits 0
```

#### 16.5.8 G-8 Baseline freeze

```gherkin
Feature: G-8 quality-baseline freeze
  Scenario: PR shrinks a baseline
    Given the PR removes 3 entries from .vulture_whitelist.py
    When the lint job runs
    Then G-8 exits 0

  Scenario: PR adds 2 entries to .vulture_whitelist.py without grow label
    Given the PR has no `vulture-whitelist-grow` label
    When the lint job runs
    Then G-8 exits 1
    And  the report names .vulture_whitelist.py and the unauthorized lines

  Scenario: PR lowers interrogate fail-under from 60 to 55
    Given the PR has no `interrogate-floor-grow` label (or label disallows lowering)
    When the lint job runs
    Then G-8 exits 1
```

### 16.6 Edge Cases

The cases below are the failure modes the §16 Gherkin AC are likely to miss. They are documented here so the test suite for the gate scripts (CLAUDE.md Build Rule #2 step 4-5) covers them explicitly.

**16.6.1 Branch model.**
- A PR opened against `feature/*` should *not* run T3 gates (G-6, G-7). The current `ci.yml` already gates Tier-3 on `base_ref in ('integration', 'main')`; §16 reuses the same conditional and inherits this behavior.
- A PR retargeted from `feature/*` to `integration` mid-flight: the next push triggers T3 gates and the PR may flip to red. Document in PR-title conventions; do not paper over with delayed enforcement.

**16.6.2 Force-push and rewrites.**
- Baselines reference file paths and function names. A force-push that renames a function makes the prior baseline entry stale. Each gate's wrapper must treat *unmatched* baseline entries as warnings, not silent passes — otherwise a rename is a free pass.
- Squashing a multi-commit branch where the first commit added a baseline entry and the last removed it: the squash diff is net-neutral; G-8 sees zero growth and passes correctly.

**16.6.3 Generated and vendored code.**
- `migrations/`, `src/stronghold/types/openapi/` (if present in future), and any `__generated__.py` files are excluded by every gate. Exclusions live in **one place per gate**: pyproject for interrogate, `.jscpd.json` for jscpd, `--exclude` flags for vulture/xenon. Cross-gate exclusion drift is the most common §16 failure mode; a PR that excludes a path in one gate but not another should fail at review.
- Vendored dependencies (`vendor/`, `third_party/`) are excluded from G-1..G-5 unconditionally. G-6/G-7 never look at non-`src/stronghold/` paths.

**16.6.4 Empty diffs and docs-only PRs.**
- A docs-only PR that touches `*.md` only: G-1..G-5 see an empty changed-files list. Each gate must short-circuit to exit-0 instead of running over the empty input (mutmut and the LLM judge default to scanning *everything* when given an empty list — the wrapper guards against this).
- Workflow-only PRs (touching `.github/workflows/*.yml`): same short-circuit, plus a hard requirement that the PR description names the rationale (catches accidental gate-disable PRs).

**16.6.5 Mutation testing on async code.**
- mutmut's "killed by tests" heuristic is unreliable on `async def` functions whose tests use `pytest-asyncio` because event-loop teardown order can mask reverted-operator mutants. The 5pp tolerance band in §16.4.6 is calibrated for this. Modules with >50% async surface area (currently `agents/base.py`, `api/routes/*`, `litellm_client.py`) get a 10pp tolerance recorded as a per-file override in `.mutation-baseline.json::tolerances`.

**16.6.6 Judge non-determinism (G-7).**
- Even at `temperature=0`, a model-server-side rolling update can shift verdicts. The dated-snapshot pin (`claude-haiku-4-5-20251001`) reduces but does not eliminate drift. The golden-set regression run (>2% drift blocks the prompt-change PR) catches the case where the *judge prompt* changes; a server-side model snapshot rotation is detected by a weekly cron that re-runs the golden set on `integration` and posts to the operator inbox.

**16.6.7 Concurrent ratchets.**
- Two PRs simultaneously raising `fail-under` (G-4) or shrinking the same baseline file (G-2): merge conflicts on the threshold/baseline are the correct outcome. Resolution is manual — neither PR auto-wins. Document in §16.10.

**16.6.8 Cost-cap interaction with judge retries.**
- G-7 retries are bounded: 1 retry per file on `429`/`5xx`. A PR with 200 changed test files at $0.0005/test exceeds the $0.10 cap; the script must process *new-or-modified-most-likely-to-be-BAD* files first (heuristic: most assertions, longest body) so a cost-truncated run still catches the highest-signal cases.

**16.6.9 First-time baseline generation.**
- A repo without a baseline file fails closed: gate refuses to run, prints `make baseline-<gate>` instructions. The first-time generation lands as a separate PR per gate (one baseline file, no other changes). This isolates the "we now believe the codebase looks like X" decision into a single reviewable diff.

**16.6.10 Stale baselines after long-lived branches.**
- A feature branch open for 2+ months on a baseline that has since shrunk on `integration`: the rebase produces a baseline file with entries `integration` no longer permits. G-8 correctly fails this PR — the entries appear as net-new from `integration`'s perspective. The fix is `make baseline-<gate>` post-rebase; this is the canonical "refresh the baseline" workflow.

### 16.7 Contracts

The interface every §16 implementation must respect. Implementations are free in their internals but must conform here so workflows, scripts, and reviewers compose without surprises.

#### 16.7.1 File layout

| Path | Owner | Format | Regen command |
|------|-------|--------|---------------|
| `.xenon-baseline.json`             | G-1 | JSON (§16.4.1) | `make baseline-xenon` |
| `.vulture_whitelist.py`            | G-2 | Python identifier list (vulture-native) | `make baseline-vulture` |
| `.jscpd.json`                      | G-3 | jscpd config | hand-edited (rare) |
| `.jscpd-baseline.json`             | G-3 | JSON (§16.4.3) | `make baseline-jscpd` |
| `pyproject.toml [tool.interrogate]` | G-4 | TOML | hand-edited at ratchet |
| `.assertion-pattern-baseline.json` | G-5 | JSON (§16.4.5) | `make baseline-assertions` |
| `.mutation-baseline.json`          | G-6 | JSON (§16.4.6) | `make baseline-mutation` (T3 only) |
| `tests/specs/assertion-judge-golden.jsonl` | G-7 | JSONL of `{test_src, expected_verdict, rationale}` | hand-curated |
| `prompts/assertion_judge_v1.md`    | G-7 | Markdown system prompt | versioned by suffix `_vN.md` |
| `scripts/xenon_with_baseline.py`   | G-1 | Python | — |
| `scripts/check_assertion_patterns.py` | G-5 | Python | — |
| `scripts/check_mutation_score.py`  | G-6 | Python | — |
| `scripts/run_assertion_judge.py`   | G-7 | Python | — |
| `scripts/check_quality_baselines.py` | G-8 | Python | — |
| `Makefile` (or `justfile`)         | all | targets `baseline-<gate>` and `gate-<gate>` | — |

#### 16.7.2 Exit-code grammar

Every gate script obeys the same three-value grammar:

| Code | Meaning | CI behaviour |
|------|---------|--------------|
| `0`  | Pass — no net-new violations vs. baseline. | Step succeeds. |
| `1`  | Fail — at least one net-new violation. | Step fails; PR blocked (Phase 2+) or warned (Phase 1). |
| `2`  | Tool/script error — malformed baseline, missing dependency, network failure. | Step fails *as a flake*; rerun-button visible; not a quality verdict. |

Anything other than `0/1/2` is a script bug. Test stubs assert on the specific exit code, not just `!= 0`.

#### 16.7.3 Output contract

Each gate script emits two channels:

1. **stdout** — human-readable summary, one line per offender plus a leading `OK:`/`FAIL:` banner. Suitable for CI log scanning.
2. **`$GATE_REPORT_PATH/<gate-id>.json`** (if env var set) — machine-readable structured report for the dashboard collector and the §16.4.8 baseline-freeze cross-check. Schema:
   ```json
   {
     "gate": "G-1",
     "status": "pass|fail|error",
     "phase": "warn|block",
     "violations": [
       {"file": "...", "line": 42, "kind": "RANK_D", "permitted_by_baseline": false, "detail": "..."}
     ],
     "metrics": {"total_blocks_scanned": 1842, "wall_time_s": 6.3}
   }
   ```

Reports land in `$GITHUB_WORKSPACE/.gate-reports/` so a single artifact upload step in `ci.yml` collects them all.

#### 16.7.4 Make targets

```
make baseline-xenon         # writes .xenon-baseline.json
make baseline-vulture       # writes .vulture_whitelist.py
make baseline-jscpd         # writes .jscpd-baseline.json
make baseline-assertions    # writes .assertion-pattern-baseline.json
make baseline-mutation      # writes .mutation-baseline.json (slow; T3)
make baseline-all           # all of the above

make gate-xenon             # runs the gate script locally with the same flags as CI
make gate-vulture
make gate-jscpd
make gate-interrogate
make gate-assertions
make gate-mutation
make gate-judge             # G-7; requires ROUTER_API_KEY env
make gate-baselines         # G-8 cross-check
make gates-all              # all gates, in CI's order
```

A pre-commit hook calls `make gates-all`, which short-circuits to T1-only if the working dir is on a `feature/*`-pointed branch.

#### 16.7.5 Label contracts

GitHub PR labels that toggle gate behaviour. Each is restricted to operator-tier reviewers via branch-protection rules (`Required reviews from CODEOWNERS`).

| Label | Suspends | Required justification |
|-------|----------|-----------------------|
| `xenon-baseline-grow`        | G-1 baseline-grow check | Link to refactor PR scheduled within 30 days |
| `vulture-whitelist-grow`     | G-2 whitelist-grow check + G-8 | `## Whitelist additions` heading in PR body |
| `jscpd-baseline-grow`        | G-3 clone-pair-grow check + G-8 | Justification + dedup-PR linked |
| `interrogate-floor-grow`     | G-4 floor-lower check + G-8 | Architectural rationale (rare; default deny) |
| `assertion-pattern-baseline-grow` | G-5 baseline-grow check + G-8 | Linked rewrite issue |
| `mutation-tolerance-grow`    | G-6 tolerance-grow check  | Async-surface justification |
| `judge-override`             | G-7 BAD-block             | `## Judge override` heading explaining why the verdict is wrong |

The labels are *audit*, not *bypass*: they remain on the PR, are visible in the merge log, and are reported in the §16.10 quarterly review.

### 16.8 CI Workflow Wiring

The shape of the deltas to `.github/workflows/ci.yml`. This subsection is the *spec* — actual workflow edits land in implementation PRs, one gate per PR, per CLAUDE.md Build Rule #10 step 12.

#### 16.8.1 Job topology

```
┌─────────────────────────────────────────────────────────────────┐
│ ci.yml                                                          │
│                                                                 │
│  lint  ──┐                                                      │
│          ├─► (existing: ruff, mypy, bandit)                     │
│          ├─► G-1 xenon-with-baseline                            │
│          ├─► G-2 vulture                                        │
│          ├─► G-3 jscpd                                          │
│          ├─► G-4 interrogate                                    │
│          ├─► G-5 assertion-pattern-lint  (changed tests only)   │
│          └─► G-8 baseline-freeze                                │
│                                                                 │
│  security ─► (existing: warden+sentinel+gate, adversarial, ...) │
│  sast ────► (existing: bandit-r, semgrep, gitleaks, hadolint)   │
│  test ────► (existing: tier-1/2/3 pytest + coverage)            │
│                                                                 │
│  ┌── only when base_ref ∈ {integration, main} ────────────────┐ │
│  │  mutation ─► G-6 mutmut on changed src files               │ │
│  │  judge ───► G-7 LLM assertion judge on changed test files  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

G-1..G-5 + G-8 sit inside the existing `lint` job (single checkout, single Python install — the gates are cheap). G-6 and G-7 each get their own job because they have distinct setup costs (mutmut needs the full test environment; the judge needs `ROUTER_API_KEY`).

#### 16.8.2 Step-shape (warn-only Phase 1)

```yaml
- name: "G-X <gate-name> (warn-only baseline)"
  id: gate-X
  continue-on-error: true
  env:
    GATE_REPORT_PATH: ${{ github.workspace }}/.gate-reports
  run: |
    mkdir -p "$GATE_REPORT_PATH"
    python scripts/<gate>.py --baseline .<gate>-baseline.json <args>
```

#### 16.8.3 Step-shape (blocking Phase 2)

```yaml
- name: "G-X <gate-name>"
  id: gate-X
  env:
    GATE_REPORT_PATH: ${{ github.workspace }}/.gate-reports
  run: |
    mkdir -p "$GATE_REPORT_PATH"
    python scripts/<gate>.py --baseline .<gate>-baseline.json <args>
```

The only diff between Phase 1 and Phase 2 is `continue-on-error: true` — which is *exactly* the `|| true` anti-pattern §16.3.3 names, but explicit instead of implicit. Promotion to blocking is a one-line PR.

#### 16.8.4 Report aggregation

After all gates, a single step uploads `.gate-reports/*.json` as a workflow artifact:

```yaml
- name: "Upload gate reports"
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: gate-reports
    path: .gate-reports/
```

A separate workflow (`gate-dashboard.yml`, runs on schedule + on `integration` push) collects historical reports and renders a per-gate trend dashboard. The dashboard is **read-only** — no enforcement decisions are made from it.

#### 16.8.5 Label-driven step skips

Steps that respect grow-labels read them via `${{ contains(github.event.pull_request.labels.*.name, 'X') }}`. Pattern:

```yaml
- name: "G-2 vulture (whitelist-shrink-only)"
  if: "!contains(github.event.pull_request.labels.*.name, 'vulture-whitelist-grow')"
  run: vulture src/stronghold/ .vulture_whitelist.py --min-confidence 100
```

When the label is present, the step is skipped *and* the G-8 baseline-freeze step's report records the suspension under `metrics.label_overrides`. Quarterly reviews (§16.10) read this field.

#### 16.8.6 Concurrency and caching

- `concurrency: ci-${{ github.ref }}` already cancels superseded runs (preserved).
- `pip` cache is shared across jobs via `actions/setup-python@v5`'s built-in cache (already used).
- mutmut has its own incremental cache — `~/.mutmut-cache` — keyed on the post-checkout SHA of `src/stronghold/`. Cache hit: skip files whose mutation results are still valid. Cache miss: full run within wall-time budget.

#### 16.8.7 Local dev parity

Pre-commit hook (`.pre-commit-config.yaml`) runs the T1 gates — G-1..G-5 and G-8 — using the same `make gate-*` targets CI invokes. T3 gates are explicitly not pre-commit-runnable (cost). Developers running `make gate-mutation` locally is a documented workflow but not enforced.
