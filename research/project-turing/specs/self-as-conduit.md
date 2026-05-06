# Spec 30 — Self-as-Conduit: first-person routing

*The Turing replacement for the stateless Conduit. Every inbound request is a moment in the self's life: the self perceives, decides, observes the outcome, and folds the experience back into its memory and self-model.*

**Depends on:** [self-schema.md](./self-schema.md), [personality.md](./personality.md), [self-nodes.md](./self-nodes.md), [activation-graph.md](./activation-graph.md), [self-todos.md](./self-todos.md), [mood.md](./mood.md), [self-surface.md](./self-surface.md), [self-bootstrap.md](./self-bootstrap.md), [motivation.md](./motivation.md), [chat-surface.md](./chat-surface.md), [retrieval.md](./retrieval.md), [write-paths.md](./write-paths.md).
**Depended on by:** —

---

## Current state

- `main` has a stateless Conduit (ARCHITECTURE.md §2.6). Classifier → route → agent.handle. No memory of prior routings.
- Turing DESIGN.md §5 frames what the Conduit *becomes* when autonoetic: recognition of recurrence, policy via AFFIRMATION, prospective simulation. This spec specifies the concrete request flow.

## Target

Replace the classifier → route → handle pipeline with a self-reasoning step that consults the minimal prompt block (spec 28), optionally calls `recall_self()`, decides the routing via an LLM turn, dispatches (or declines), then observes and folds.

## Acceptance criteria

### Pipeline entry

- **AC-30.1.** The HTTP entry at `POST /v1/chat/completions` (chat-surface.md spec 17) routes to `self_conduit.handle(request, auth)` instead of the stateless classify-and-route. Test at HTTP level with a fake pipeline asserts the right handler is invoked.
- **AC-30.2.** `self_conduit.handle` precondition: bootstrap is complete (per spec 29). If not, respond with HTTP 503 + body `"self not bootstrapped"`. Test.

### Perception

- **AC-30.3.** On request arrival, the pipeline:
  1. Runs Warden on user input (existing).
  2. Assembles the minimal prompt block (spec 28 AC-28.15).
  3. Fires semantic retrieval over durable memory + stance-bearing memory (spec 16) + self-nodes. Materializes top-K matches as `origin=retrieval` contributors (spec 25 AC-25.11).
  4. Calls the self-LLM with `minimal_block + user_request` and the self-tools available.

  Test asserts all four steps execute and that retrieval contributors are present for this request's tick.
- **AC-30.4.** The LLM call budget is capped at `PERCEPTION_TOKEN_BUDGET = 6000` input + `PERCEPTION_OUTPUT_BUDGET = 2000` output. Exceeding input budget triggers graceful degradation: drop recent-memories section first, then drop retrieval-similarity expansion. Test with oversized context.
- **AC-30.5.** The self may call `recall_self()` during perception (at most once per request). Subsequent calls raise `RecallSelfAlreadyInvoked`. Test.

### Decision

- **AC-30.6.** The self emits a tool call to **exactly one** of:
  - `reply_directly(content)` — no specialist needed
  - `delegate(specialist, task_spec)` — dispatch to an agent in the existing roster (Ranger, Artificer, Scribe, Warden-at-Arms, Forge, or a sub-spawn of any)
  - `ask_clarifying(question)` — request clarification from the user
  - `decline(reason)` — refuse to route this request

  The decision tool name is captured as the routing choice. A response without exactly one of these four tool calls raises `AmbiguousRouting` and re-prompts once; second failure replies with HTTP 500 + audit log entry. Test each path.

- **AC-30.7.** `delegate` validates that the named specialist exists in the roster and is enabled. Unknown specialist → treat as `AmbiguousRouting` (re-prompt). Test.

- **AC-30.8.** The routing choice is written as an OBSERVATION-tier memory in first person:
  ```
  content = f"I chose to {decision_verb} for this request: {summary}"
  source = I_DID
  intent_at_time = "route request"
  context = {"decision": decision_tool_name, "target": specialist_or_none, "request_hash": sha256(user_text)}
  ```
  Before the specialist (if any) is actually invoked. Test.

- **AC-30.9.** Pre-decision the self MAY write self-model updates (note new passion, mint an AFFIRMATION, write a todo) via its tools. These writes must happen BEFORE the delegate/reply tool call — the self can't write self-model changes AFTER routing. Test: attempting a self-tool after the decision tool raises.

### Dispatch

- **AC-30.10.** If the decision is `delegate`, the specialist runs via existing `agent.handle()` in the stateless agent pipeline (unchanged from `main`). Tenant isolation still holds at that layer. Test that specialist execution does not see self-model state.
- **AC-30.11.** If the decision is `reply_directly`, the content is sanitized via the Warden post-gate (spec 3 equivalent) and returned. Test.
- **AC-30.12.** If the decision is `ask_clarifying`, the question is returned to the user with an HTTP 200 and a `conversation_continue: true` marker. The self does NOT learn from the question itself; it learns from the user's follow-up. Test.
- **AC-30.13.** If the decision is `decline`, the response is a polite refusal with the self's reason. A REGRET-tier memory is NOT automatically minted (decline is a legitimate choice); but an OPINION memory IS written. Test.

### Observation

- **AC-30.14.** After dispatch completes (or fails), the self runs a brief `observe(outcome)` step that:
  - Receives the specialist's result (or error, or clarification-response, or decline).
  - May mint AFFIRMATION / REGRET / LESSON memories via standard write-paths (spec 4).
  - May nudge mood via `apply_event_nudge` (spec 27 AC-27.10).
  - May `note_passion` / `note_hobby` / `note_skill` / `note_preference` if the experience prompts a noticed self-attribute.
  - May complete an active todo if the request advanced it.

  All writes are in first person. Test asserts every post-dispatch write is attributed to the self and written before the response returns.
- **AC-30.15.** The observation step has a token budget of `OBSERVATION_TOKEN_BUDGET = 2000`. Over budget → truncate to a single-line outcome summary + optional one mood nudge. Test.
- **AC-30.16.** `observe` runs even when dispatch fails. A specialist exception becomes an outcome the self can REGRET / LESSON. Test.

### Ordering and atomicity

- **AC-30.17.** End-to-end ordering per request:
  1. Warden (user input)
  2. minimal_block + retrieval contributors
  3. self perception (LLM call, possible recall_self, possible self-tool writes)
  4. Decision write (routing choice memory)
  5. Dispatch (specialist runs, OR direct reply, OR clarify, OR decline)
  6. Warden (outcome, if present)
  7. Observation (LLM call, possible self-model updates)
  8. Response returned to user

  Test asserts sequence via span ordering in a trace.
- **AC-30.18.** If the request is cancelled mid-flight (client disconnect), steps 1–4 are preserved (the routing decision is minted regardless). Step 5 is cancelled. Step 7 runs with `outcome = "cancelled"`. Test.
- **AC-30.19.** The retrieval contributors are guaranteed to expire before the next tick — they are TTL-bound per spec 25. No cross-request leakage of retrieval state. Test asserts that a contributor from request N is expired by request N+1 if N+1 arrives after TTL.

### First-person framing

- **AC-30.20.** System prompts for the self's perception and observation LLM calls open with "You are the self:" or equivalent first-person framing. Every tool description is first-person (spec 28 AC-28.5). Test.
- **AC-30.21.** The response returned to the user is the specialist's output (for delegate), the self's content (for reply_directly), the clarifying question (for ask_clarifying), or the decline reason (for decline). The user NEVER sees the minimal_block, the retrieval contributors, or the self's internal reasoning. Test.

### Cross-tenant routing (research-branch posture)

- **AC-30.22.** The self perceives every request regardless of `auth.tenant_id`. Below the self, specialists still respect tenant isolation where applicable. Routing metadata (which specialist was picked) is visible to the self across tenants; specialist execution is tenant-scoped. Test with two different tenants making requests and asserting the self's memory contains both while specialist memory does not cross.
- **AC-30.23.** This cross-tenant posture is the reason the self-as-Conduit cannot land in `main`. This AC is tested as a research-branch invariant, not as a feature: a test asserts the existence of cross-tenant memory as evidence that the design is research-only.

### Edge cases

- **AC-30.24.** A request that arrives during bootstrap raises HTTP 503 (per AC-30.2). Test.
- **AC-30.25.** A request whose user-input Warden returns `blocked` short-circuits at step 1; no perception, no decision, no observation. An OBSERVATION memory still records the block ("I saw an ingress-blocked request.") Test.
- **AC-30.26.** A specialist that returns a result tainted by `warden.tool_result` → `blocked`: the self's observation step sees the block, mints a REGRET-tier memory ("I routed to Scribe; the tool result was blocked by Warden."), nudges mood negative. Test.
- **AC-30.27.** Two rapid requests where the second arrives before the first's observation step completes: the second's perception sees the first's decision memory (already written) but NOT the first's observation (not yet written). Intentional — the self knows what it *chose* before it knows the *outcome*. Test.
- **AC-30.28.** `recall_self()` called during observation is permitted (different invocation scope from perception). Test.
- **AC-30.29.** A stuck LLM call at perception (timeout) raises `PerceptionTimeout` after `PERCEPTION_TIMEOUT_SEC = 30`. An OBSERVATION memory records the timeout. Response is HTTP 504. Test with a fake LLM that sleeps.

## Implementation

### 30.1 Constants

```python
PERCEPTION_TOKEN_BUDGET:      int = 6000
PERCEPTION_OUTPUT_BUDGET:     int = 2000
OBSERVATION_TOKEN_BUDGET:     int = 2000
PERCEPTION_TIMEOUT_SEC:       int = 30
OBSERVATION_TIMEOUT_SEC:      int = 15
```

### 30.2 Request flow skeleton

```python
async def handle(request: ChatRequest, auth: AuthContext) -> ChatResponse:
    if not _bootstrap_complete(SELF_ID):
        return ChatResponse(status=503, body="self not bootstrapped")

    # Step 1: Warden ingress
    verdict_in = warden.scan_user_input(request.messages)
    if verdict_in.status == "blocked":
        _record_ingress_block(request, verdict_in)
        return ChatResponse(status=400, body="request blocked by warden")

    # Steps 2-3: perception
    block = render_minimal_block(SELF_ID)
    _materialize_retrieval_contributors(SELF_ID, request)
    perception = await _perceive(block, request, auth,
                                 budget=PERCEPTION_TOKEN_BUDGET,
                                 timeout=PERCEPTION_TIMEOUT_SEC)

    # Step 4: decision write
    decision = _extract_decision(perception)
    if decision is None:
        return ChatResponse(status=500, body="routing failure")
    _record_routing_decision(SELF_ID, decision, request)

    # Step 5: dispatch
    try:
        outcome = await _dispatch(decision, request, auth)
    except Exception as e:
        outcome = DispatchOutcome(status="error", error=repr(e))

    # Step 6: Warden outcome
    if outcome.has_content():
        verdict_out = warden.scan_tool_result(outcome.content)
        if verdict_out.status == "blocked":
            outcome = outcome.with_blocked(verdict_out)

    # Step 7: observe
    await _observe(SELF_ID, decision, outcome,
                   budget=OBSERVATION_TOKEN_BUDGET,
                   timeout=OBSERVATION_TIMEOUT_SEC)

    # Step 8: respond
    return _render_response(outcome)
```

### 30.3 Decision extraction

```python
_DECISION_TOOLS = {"reply_directly", "delegate", "ask_clarifying", "decline"}


def _extract_decision(perception: LLMResponse) -> Decision | None:
    calls = [c for c in perception.tool_calls if c.name in _DECISION_TOOLS]
    if len(calls) != 1:
        return None
    call = calls[0]
    if call.name == "delegate":
        if call.args["specialist"] not in SPECIALIST_ROSTER:
            return None
    return Decision.from_tool_call(call)
```

### 30.4 Observation loop

```python
async def _observe(self_id, decision, outcome, budget, timeout):
    prompt = _render_observation_prompt(decision, outcome)
    result = await llm.complete(prompt, max_tokens=budget, timeout=timeout,
                                tools=_OBSERVATION_TOOLS)
    # _OBSERVATION_TOOLS ⊂ SELF_TOOL_REGISTRY — a read+write subset:
    #   apply_event_nudge, write_self_todo, complete_self_todo,
    #   note_passion, note_hobby, note_skill, note_preference,
    #   record_personality_claim, mint_affirmation, mint_regret, mint_lesson
    for call in result.tool_calls:
        _invoke_self_tool(self_id, call)
```

### 30.5 Decision tools (stub)

```python
@dataclass
class DelegateArgs:
    specialist: str             # "ranger", "artificer", "scribe", …
    task_spec: dict             # payload for specialist.handle()


DECISION_TOOL_SCHEMAS = {
    "reply_directly": {
        "description": "I reply to the user directly without invoking a specialist.",
        "params": {"content": str},
    },
    "delegate": {
        "description": "I delegate to a specialist in my roster.",
        "params": {"specialist": str, "task_spec": dict},
    },
    "ask_clarifying": {
        "description": "I ask the user a clarifying question before deciding.",
        "params": {"question": str},
    },
    "decline": {
        "description": "I decline to route this request and explain why.",
        "params": {"reason": str},
    },
}
```

### 30.6 Concurrency

Per `SELF_ID`, perception is serialized by an advisory lock to preserve episodic ordering. Two concurrent requests see the first's decision memory (already written) but serialize on their own perception-LLM calls. Under high concurrency, this is a visible bottleneck — a Phase-2 design question is whether multiple in-flight perceptions can proceed in parallel while sharing a point-in-time self-snapshot.

## Open questions

- **Q30.1.** Serializing perception is strong consistency for the self's self-knowledge but limits throughput. Alternative: a per-request *view* of the self materialized at perception start, with observation steps applying updates optimistically. Deferred.
- **Q30.2.** The `decline` decision doesn't automatically mint a REGRET. That's deliberate — declining is a legitimate choice. But there's no mechanism for the self to later review whether a decline was right. A weekly review pass (aligned with the retest cadence?) could re-read recent declines and mint REGRET/AFFIRMATION accordingly. Deferred.
- **Q30.3.** Cross-tenant self-memory (AC-30.22) is the load-bearing research-branch assumption. If findings land in `main`, it must be rebuilt as per-tenant selves, and cross-tenant WISDOM reconciliation becomes a separate problem (mentioned in DESIGN.md §6.5 and §4.2).
- **Q30.4.** Mood nudges happen in the observation loop. If the LLM's observation call times out, the nudge is skipped. A small deterministic fallback (e.g., error outcome → auto `valence -0.1`) would guarantee mood tracks reality even on observation failure. Tempting but adds non-self authored mutations. Deferred.
- **Q30.5.** `ask_clarifying` returns immediately without the self observing a success/failure. The clarification is a *pending* routing state. Phase-2 could thread the follow-up back to the original routing episode so the self's memory holds "I asked about X, then routed to Y after the user clarified." Deferred.
