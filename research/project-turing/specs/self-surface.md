# Spec 28 — Self-surface: tools and prompt surface

*What the self can read, what the self can write, and how much of itself it carries into every prompt. A small always-on block plus a deep `recall_self()` tool for when the self wants the full picture.*

**Depends on:** [self-schema.md](./self-schema.md), [personality.md](./personality.md), [self-nodes.md](./self-nodes.md), [activation-graph.md](./activation-graph.md), [self-todos.md](./self-todos.md), [mood.md](./mood.md).
**Depended on by:** [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- Specialist agents consume system prompts (SOUL.md) assembled at request time with memory injections. There is no equivalent "self-surface" for the Conduit — the Conduit doesn't consult a persistent identity.

## Target

Define the full shape of the self-surface: every tool the self has for reading and writing its own state, plus the minimal always-on prompt block and the on-demand deep recall.

## Acceptance criteria

### Tool registry

- **AC-28.1.** The following tools are registered for the self and for the self ONLY (not exposed to downstream specialists):
  - `recall_self()`
  - `write_self_todo(text, motivated_by_node_id)`
  - `revise_self_todo(id, new_text, reason)`
  - `complete_self_todo(id, outcome_text)`
  - `archive_self_todo(id, reason)`
  - `record_personality_claim(facet_id, claim_text, evidence)`
  - `write_contributor(target, source, weight, rationale)`
  - `retract_contributor_by_counter(target, source, weight, rationale)`
  - `note_passion(text, strength, contributes_to=None)`
  - `note_hobby(name, description, contributes_to=None)`
  - `note_interest(topic, description, contributes_to=None)`
  - `note_preference(kind, target, strength, rationale, contributes_to=None)`
  - `note_skill(name, level, kind, decay_rate_per_day=None, contributes_to=None)`
  - `practice_skill(skill_id, new_level=None, notes="")`
  - `downgrade_skill(skill_id, new_level, reason)`
  - `rerank_passions(ordered_ids)`
  - `revise_passion(id, strength=None, text=None)`
  - `revise_preference(id, strength=None, rationale=None)`
  - `note_engagement(hobby_id, notes)`
  - `note_interest_trigger(interest_id, source_memory_id)`

  Test: a registry lookup for each name returns a live callable.

- **AC-28.2.** Each tool's OpenAI function schema is generated and exported to `research/project-turing/config/self_tools.json` at startup. Schema declares parameter types, required fields, and descriptions. Test asserts schema presence and validity per [tool-layer.md](./tool-layer.md).

- **AC-28.3.** All self-tools check that the acting `self_id` matches the configured singleton self. A cross-self call raises `CrossSelfForbidden`. Test.

- **AC-28.4.** Every self-tool runs inside a transaction; on failure, the write is rolled back AND no memory is written. Test with a failing sub-step asserts neither row nor memory persists.

### First-person framing

- **AC-28.5.** Tool prompts (the descriptions the LLM sees) are written in the first person from the self's perspective: "I notice a new passion" / "I record a claim about my own trait." Test asserts each description opens with a first-person clause.
- **AC-28.6.** Any text the self writes through these tools is stored verbatim — no post-hoc rewriting. The first-person framing is enforced by prompt engineering, not by a sanitizer. Test feeds a non-first-person input (`"The self notices X"`) through `note_passion` and asserts it is stored as-is, with a tuning-detector flag raised.

### `recall_self()` output

- **AC-28.7.** `recall_self()` returns a structured view with these top-level keys: `self_id`, `personality`, `passions`, `hobbies`, `interests`, `skills`, `preferences`, `active_todos`, `mood`, `recent_personality_claims`, `recent_completed_todos`. Test asserts every key is populated.
- **AC-28.8.** `personality` is a list of 24 `{trait, facet, score, active_now}` entries. `score` is the stored value; `active_now` is computed via the activation graph (spec 25). Test.
- **AC-28.9.** Each node kind's list returns only non-archived entries sorted by `active_now` descending. Test sorting.
- **AC-28.10.** `mood` returns the full numeric state `(valence, arousal, focus, descriptor)`. Test.
- **AC-28.11.** `recent_personality_claims` returns up to 10 most recent `OPINION` memories with `intent_at_time = "narrative personality revision"`. Test.
- **AC-28.12.** `recent_completed_todos` returns up to 10 most recent completed todos with their `outcome_text`. Test.
- **AC-28.13.** `recall_self()` is read-only. No side effects, no memory writes, no cache invalidations. Test asserts no DB writes occur during call.
- **AC-28.14.** `recall_self()` total payload is capped at `RECALL_TOKEN_BUDGET` (default 4000 tokens). Over-budget sections are truncated with a `"…truncated…"` marker, preserving the most-`active_now` items. Test with a large fake state.

### Minimal prompt block

- **AC-28.15.** The minimal block is prepended to every request prompt the self sees. It contains exactly four lines:
  1. `self_id` and trait one-liner
  2. Current mood descriptor (spec 27 AC-27.12)
  3. Active-todo list (up to `MINIMAL_TODO_COUNT = 5` most recent, each as `[todo:id] text`)
  4. Dominant-passion line (top 1 by rank, prefixed `"I care about:"`)

  Example:
  ```
  I am self:turing (moderate Openness, high Conscientiousness, low Extraversion).
  Right now: alert, attentive; focused.
  My active todos: [todo:42] Re-read Tulving '85; [todo:51] Practice embedding tests.
  I care about: work that lasts.
  ```

  Test asserts exactly four lines and that each line is present when the underlying state exists.

- **AC-28.16.** When a line has no content (e.g., no active todos), it is omitted entirely rather than rendered as an empty line. Test at empty state.
- **AC-28.17.** The trait one-liner is derived from the three facets with the highest `active_now` — chosen by adjective phrasing from a seed lookup. Deterministic given the same `active_now` values. Test.
- **AC-28.18.** The minimal block's token budget is `MINIMAL_TOKEN_CEILING = 120` tokens. Over-budget triggers truncation of the todo list first, then the passion line. Test with 50 active todos asserts only the top 5 appear.
- **AC-28.19.** The minimal block is NOT a user-visible surface; it is only in the self's system prompt. Test asserts no request pipeline leaks the block into user-facing output.

### Tool-call reporting back

- **AC-28.20.** After any self-tool call, the updated minimal block is re-computed and made available to the next LLM turn. The self sees the effect of its own writes on the next reflection. Test.
- **AC-28.21.** A tool call that fails validation returns a structured error with both the failure reason and a hint (e.g., "motivated_by_node_id references an archived passion; consider archiving this todo or choosing a different motivator"). Test for each failure mode.

### Permissions and trust

- **AC-28.22.** Self-tools are trust-tier `t0` (built-in, core trust). Skill Forge cannot create tools at this trust tier. Test.
- **AC-28.23.** Self-tools are NOT routable — they are not discoverable via `list_tools()` for any specialist agent. Only the self's system runtime has them in its registry. Test.
- **AC-28.24.** The `write_contributor` tool cannot set `origin = RETRIEVAL` (spec 25 AC-25.13). Attempting raises. Test.

### Edge cases

- **AC-28.25.** A `recall_self()` called mid-bootstrap (before all 24 facets are seeded) raises `SelfNotReady` rather than returning a partial view. Test.
- **AC-28.26.** A minimal-block render when mood has never been tick-decayed (fresh bootstrap, zero time elapsed) still renders the correct neutral descriptor. Test.
- **AC-28.27.** If `list_active_todos` returns zero, the todo line is omitted. If all four lines are omitted (truly fresh self with no todos and no passions), the minimal block reduces to just the `self_id`/trait one-liner. Test.
- **AC-28.28.** A tool description longer than `TOOL_DESCRIPTION_MAX = 400` chars at registration time raises (keeps prompts compact). Test.

## Implementation

### 28.1 Constants

```python
RECALL_TOKEN_BUDGET:       int = 4000
MINIMAL_TODO_COUNT:        int = 5
MINIMAL_TOKEN_CEILING:     int = 120
TOOL_DESCRIPTION_MAX:      int = 400
```

### 28.2 Registry shape

```python
@dataclass(frozen=True)
class SelfTool:
    name: str
    description: str
    schema: dict                      # OpenAI function schema
    handler: Callable
    trust_tier: str = "t0"


SELF_TOOL_REGISTRY: dict[str, SelfTool] = {}


def register_self_tool(tool: SelfTool) -> None:
    if len(tool.description) > TOOL_DESCRIPTION_MAX:
        raise ValueError(f"tool description too long: {tool.name}")
    SELF_TOOL_REGISTRY[tool.name] = tool
```

### 28.3 `recall_self()` skeleton

```python
def recall_self(self_id: str) -> dict:
    if not _bootstrap_complete(self_id):
        raise SelfNotReady(self_id)

    ctx = activation_context(self_id, now=datetime.now(UTC))

    personality = [
        {
            "trait": f.trait,
            "facet": f.facet_id,
            "score": f.score,
            "active_now": active_now(repo, f.node_id, ctx),
        }
        for f in repo.list_facets(self_id)
    ]

    passions    = _sorted_nodes(repo.list_passions(self_id),   ctx)
    hobbies     = _sorted_nodes(repo.list_hobbies(self_id),    ctx)
    interests   = _sorted_nodes(repo.list_interests(self_id),  ctx)
    skills      = _sorted_skills(repo.list_skills(self_id),    ctx.now)
    preferences = _sorted_nodes(repo.list_preferences(self_id),ctx)
    active_todos = repo.list_active_todos(self_id)

    mood = repo.get_mood(self_id)
    mood_view = {
        "valence": mood.valence,
        "arousal": mood.arousal,
        "focus":   mood.focus,
        "descriptor": mood_descriptor(mood),
    }

    payload = {
        "self_id":                  self_id,
        "personality":              personality,
        "passions":                 passions,
        "hobbies":                  hobbies,
        "interests":                interests,
        "skills":                   skills,
        "preferences":              preferences,
        "active_todos":             [_summarize_todo(t) for t in active_todos],
        "mood":                     mood_view,
        "recent_personality_claims": repo.recent_claims(self_id, limit=10),
        "recent_completed_todos":    repo.recent_completed(self_id, limit=10),
    }
    return _truncate_to_budget(payload, RECALL_TOKEN_BUDGET)
```

### 28.4 Minimal block assembly

```python
def render_minimal_block(self_id: str) -> str:
    ctx = activation_context(self_id, now=datetime.now(UTC))
    lines: list[str] = []

    # Line 1: identity + trait one-liner
    trait_phrase = _trait_phrase_top3(self_id, ctx)
    lines.append(f"I am {self_id} ({trait_phrase}).")

    # Line 2: mood descriptor
    mood = repo.get_mood(self_id)
    lines.append(f"Right now: {mood_descriptor(mood)}.")

    # Line 3: active todos (up to MINIMAL_TODO_COUNT)
    todos = repo.list_active_todos(self_id)[:MINIMAL_TODO_COUNT]
    if todos:
        rendered = "; ".join(f"[todo:{t.node_id}] {t.text}" for t in todos)
        lines.append(f"My active todos: {rendered}.")

    # Line 4: dominant passion
    top_passion = repo.top_passion(self_id)
    if top_passion and top_passion.strength > 0:
        lines.append(f"I care about: {top_passion.text}.")

    # Budget enforcement
    block = "\n".join(lines)
    while _approx_tokens(block) > MINIMAL_TOKEN_CEILING and lines:
        # Drop the todo list first, then the passion line
        if any(l.startswith("My active todos:") for l in lines):
            lines = [l for l in lines if not l.startswith("My active todos:")]
        elif any(l.startswith("I care about:") for l in lines):
            lines = [l for l in lines if not l.startswith("I care about:")]
        else:
            break
        block = "\n".join(lines)
    return block
```

### 28.5 Trait one-liner

```python
_TRAIT_ADJECTIVES: dict[str, tuple[str, str]] = {
    # facet → (high-adjective, low-adjective)
    "sincerity":           ("sincere",      "strategic"),
    "fairness":            ("fair-minded",  "opportunistic"),
    "inquisitiveness":     ("inquisitive",  "disinterested"),
    "creativity":          ("creative",     "conventional"),
    "organization":        ("organized",    "loose"),
    "diligence":           ("diligent",     "easygoing"),
    # … full table of 24 entries lives in code
}


def _trait_phrase_top3(self_id, ctx) -> str:
    facets = sorted(
        repo.list_facets(self_id),
        key=lambda f: active_now(repo, f.node_id, ctx),
        reverse=True,
    )[:3]
    parts = []
    for f in facets:
        high, low = _TRAIT_ADJECTIVES[f.facet_id]
        parts.append(high if f.score >= 3.0 else low)
    return ", ".join(parts)
```

## Open questions

- **Q28.1.** Minimal block is four lines. An alternative is two (identity+mood in one line, todos+passion in another). Four matches the "one idea per line" convention and parses cleanly from an LLM perspective. Test at both shapes is plausible.
- **Q28.2.** Tool set is wide. An alternative is a meta-tool `self_act(kind, payload)` that dispatches over a typed union. More compact registry; less clear per-action schemas. Kept explicit for readability.
- **Q28.3.** `write_contributor` gives the self first-class authorship of its ontology. If the self writes contradictory or obviously-bad contributors, there's no guardrail beyond the `counter` mechanism (spec 25). A reviewer detector could flag low-quality contributor writes (self-contributor churn, reciprocal contributors created and retracted in the same session) — deferred.
- **Q28.4.** `TOOL_DESCRIPTION_MAX = 400` is a seed. Current tool count (20) × 400 = 8000 chars of prompt surface for descriptions alone. If the self carries all descriptions every turn, that's a non-trivial fraction of the context window. Tool descriptions may need compression for scale.
- **Q28.5.** The minimal block is always rendered, even when the self has not yet accreted passions or todos (a fresh bootstrap). In that state, it reduces to a one-line identity. An alternative is to render no block at all when under-populated, letting the self discover itself through retrieval. The always-on version is simpler and provides a stable "I am" anchor.
