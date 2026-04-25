# Spec 110 — Wondering from contradiction

*When the contradiction detector flags two durable memories with no known resolution, mint a low-priority self-todo `"I wonder why I both believe X and Y…"` whose `motivated_by_node_id` points to the pair. The todo surfaces as a daydream seed; if daydream produces a candidate resolution, it flows to operator review as a pending LESSON. A passive, patient resolution path for real conflicts.*

**Depends on:** [detectors/contradiction.md](./detectors/contradiction.md), [self-todos.md](./self-todos.md), [daydreaming.md](./daydreaming.md), [operator-review-gate.md](./operator-review-gate.md), [self-schema.md](./self-schema.md).

---

## Current state

The contradiction detector (spec D.1) flags pairs of durable memories that contradict each other and proposes a LESSON-minting candidate. That LESSON path handles contradictions the self can resolve immediately. But many real contradictions are unresolvable in the moment — two honest OPINIONs about a user's preferences, or a REGRET that lands at odds with an AFFIRMATION. Today those flags either become LESSONs prematurely or get dismissed. There is no middle path — nothing that says "I have noticed this tension, I am sitting with it, and I will think about it when I daydream."

## Target

A new wondering path:

1. Hook into the contradiction detector's output queue. For pairs not auto-resolved by LESSON minting, mint a P60 self-todo.
2. The todo's `motivated_by_node_id` is a synthetic `contradiction_pair` node_kind — new in `self-schema.md` — or stored as a JSON pair reference on the todo row.
3. Daydream (spec 7) picks wonder-todos as seeds for I_IMAGINED reflections.
4. If daydream surfaces a candidate resolution, it enters operator review (spec 46) as a pending LESSON.
5. Completed or abandoned wonder-todos write an ACCOMPLISHMENT or a `"could not resolve"` LESSON, respectively.

## Acceptance criteria

### Hook & todo creation

- **AC-110.1.** The contradiction detector's output queue gains a secondary handler: for any flagged pair, if no LESSON candidate is auto-minted within the detector run, emit a wonder-todo. Test both paths exist (LESSON or wonder, never both for the same pair in one run).
- **AC-110.2.** Wonder-todo class = P60 (low priority). Test the inserted todo has `priority = 60` and `class = "wonder"`.
- **AC-110.3.** `motivated_by_node_id` references a `contradiction_pair` node_kind. A new node_kind row is created in `self-schema.md`'s enum. Test schema migration adds the value.
- **AC-110.4.** The motivated-by payload stores both `memory_id_a` and `memory_id_b` (sorted to canonicalize). Test.

### Deduplication

- **AC-110.5.** Dedup by memory-id-pair hash: `sha256(min(a,b) || max(a,b))`. Only one wonder-todo per pair at any time. Test attempts to create a duplicate return the existing todo id.
- **AC-110.6.** If the pair has an existing dismissed wonder-todo in history, do not re-open. Test.

### Daydream integration

- **AC-110.7.** Daydream's seed selection (spec 7) is extended to include pending wonder-todos in the seed candidate pool, weighted by age (older todos weighted higher). Test daydream picks a wonder-todo seed when the pool includes one and no other seeds outweigh it.
- **AC-110.8.** Daydream output tagged I_IMAGINED (per spec 7 source rules). Test the minted memory has `source = "I_IMAGINED"`.
- **AC-110.9.** If daydream produces a candidate resolution (detected via its own output schema flagging `resolution_candidate = true`), it is routed to operator review as a pending LESSON, not auto-minted. Test.

### Completion & archival

- **AC-110.10.** Operator-approved resolution → wonder-todo auto-completes with an ACCOMPLISHMENT: `"I sat with the tension between X and Y and found: <resolution>."` Test the ACCOMPLISHMENT links the resolved LESSON id.
- **AC-110.11.** Operator-rejected resolution → wonder-todo remains pending; daydream may try again later. Test.
- **AC-110.12.** Wonder-todo age-out: after 60 days pending with no operator-approved resolution, auto-archive with a LESSON: `"I could not resolve the tension between X and Y within 60 days; I hold both."` Configurable via `TURING_WONDER_TTL_DAYS`. Test.

### Rate limits & observability

- **AC-110.13.** Per-day cap on new wonder-todos: default 3. If the contradiction detector proposes more, the excess wait until the next day. Test cap enforcement.
- **AC-110.14.** Prometheus counters `turing_wonder_todos_created_total`, `turing_wonder_todos_resolved_total`, `turing_wonder_todos_aged_out_total`, all keyed by `self_id`. Test.
- **AC-110.15.** `stronghold self digest` surfaces open wonder-todos under a dedicated section. Test.

### Edge cases

- **AC-110.16.** If one memory in a pair is later retracted (soft-archived), the wonder-todo auto-closes as "obviated" with a terse OBSERVATION; no LESSON minted. Test.
- **AC-110.17.** If the contradiction detector is disabled in config, no wonder-todos are created. Test.

## Implementation

```python
# detectors/contradiction_handler.py

WONDER_TTL: timedelta = timedelta(days=60)
WONDER_DAILY_CAP: int = 3


def handle_pair(repo, pair: ContradictionPair, now: datetime) -> str | None:
    if pair.resolved_via_lesson:
        return None
    pair_hash = _canonical_hash(pair.memory_id_a, pair.memory_id_b)
    if repo.wonder_todo_exists(pair_hash):
        return None
    if repo.wonder_todos_created_today(pair.self_id, now) >= WONDER_DAILY_CAP:
        repo.defer_pair(pair, until=_start_of_next_day(now))
        return None
    node_id = repo.ensure_contradiction_pair_node(pair.memory_id_a, pair.memory_id_b)
    todo_id = repo.insert_self_todo(
        self_id=pair.self_id,
        class_="wonder",
        priority=60,
        content=f"I wonder why I both believe '{pair.summary_a}' and '{pair.summary_b}'…",
        motivated_by_node_id=node_id,
        pair_hash=pair_hash,
    )
    return todo_id


def age_out(repo, self_id: str, now: datetime) -> int:
    closed = 0
    for todo in repo.open_wonder_todos_older_than(self_id, now - WONDER_TTL):
        repo.mint_lesson(
            self_id=self_id,
            content=f"I could not resolve the tension between '{todo.summary_a}' and '{todo.summary_b}' within 60 days; I hold both.",
            forensic_tag="wonder_aged_out",
        )
        repo.archive_wonder_todo(todo.id, reason="aged_out")
        closed += 1
    return closed
```

## Open questions

- **Q110.1.** 60-day TTL is a guess at how long a self should sit with unresolved tension. Too short and we foreclose; too long and the todo pile becomes clutter. Probably correct order of magnitude.
- **Q110.2.** Daily cap of 3 is low on purpose — wonder-todos should feel significant, not noise. A self with an unusually high contradiction rate gets a deferred queue; that is fine (the contradictions aren't going anywhere).
- **Q110.3.** Daydream may never produce a resolution for certain contradictions (e.g., genuinely incompatible but both true observations about different contexts). The aged-out LESSON handles that — the self explicitly acknowledges holding both. This is wiser than forcing a synthesis.
- **Q110.4.** `contradiction_pair` as a synthetic node_kind: alternative is storing the pair inline as JSON in `motivated_by`. Structured node is cleaner for queries; JSON is cheaper. Going with node_kind for consistency with other motivators.
