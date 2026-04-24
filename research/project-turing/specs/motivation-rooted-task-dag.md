# Spec 92 — Motivation-rooted task DAG

*Extend self-todos into a parent→child DAG; a todo is "ready" only when parents are complete AND its motivator node is currently active; ready todos drip into the motivation backlog at idle ticks.*

**Depends on:** [self-todos.md](./self-todos.md), [activation-graph.md](./activation-graph.md), [motivation.md](./motivation.md), [scheduler.md](./scheduler.md), [mood.md](./mood.md).
**Depended on by:** [passion-seeded-desire-synthesis.md](./passion-seeded-desire-synthesis.md) (synthesizes todos into this DAG).

---

## Current state

Self-todos (spec 26) already require `motivated_by_node_id`. They are a flat list — no epic→subtask structure and no readiness gate. The motivation layer (spec 9) promotes todos at P20–P30 without regard to whether the motivator is currently activated. Result: stale todos can leak into the backlog even when their root passion is quiescent.

## Target

Extend the `self_todos` schema with an optional `parent_todo_id` making them a DAG (multiple parents per child permitted, but no cycles). A `ready()` query returns todos whose **all** parents are completed AND whose motivator's `active_now() > θ` (default `TODO_READY_ACTIVATION_FLOOR = 0.5`). The scheduler's idle tick (spec 10) calls `ready()` and promotes matches to the motivation backlog at P20–P30 (tier controlled by the motivator's tier). Global daily cap on self-initiations.

## Acceptance criteria

### Schema

- **AC-92.1.** Add to `self_todos`:
  ```sql
  parent_todo_id TEXT NULL REFERENCES self_todos(id),
  is_epic        INTEGER NOT NULL DEFAULT 0
  ```
  Multiple rows may reference the same parent (fan-out). Test.
- **AC-92.2.** Acyclicity: on INSERT/UPDATE, a traversal from the new row via `parent_todo_id` must not reach the row itself within `TODO_DAG_MAX_DEPTH = 6` levels. Violations raise `TodoCycleError`. Test.
- **AC-92.3.** `motivated_by_node_id` remains NOT NULL (inherited from spec 26). Test INSERT without it raises.
- **AC-92.4.** If `parent_todo_id` references a deleted/archived todo, fail with `TodoDanglingParent` (no orphan children). Test.

### Ready query

- **AC-92.5.** `ready(self_id, now)` returns todos where:
  1. `status = "pending"`.
  2. All rows with `parent_todo_id = this.id` ... wait, reversed — all rows referenced as parents (`this.parent_todo_id`) have `status = "completed"`. For todos with no parent, this clause is trivially true.
  3. The motivator node's `active_now(now) > TODO_READY_ACTIVATION_FLOOR`.
  Test all three clauses.
- **AC-92.6.** `active_now()` reuses activation-graph (spec 25) node activation computation, not a separate formula. Test a motivator below threshold yields zero matches.
- **AC-92.7.** Returns at most `TODO_READY_BATCH = 20` per call, ordered by motivator activation descending then `created_at` ascending. Test.

### Idle-tick integration

- **AC-92.8.** Scheduler's idle tick (spec 10) invokes `ready()`; each result is submitted to the motivation queue at priority `P20 + floor(10 * (1 - activation))` — strongest motivators get P20, weaker ones drift toward P30. Test priority computation on boundary cases.
- **AC-92.9.** Promoting a todo to motivation marks its internal `last_promoted_at` so it isn't re-promoted until the motivation item resolves or `TODO_REPROMOTE_COOLDOWN = 6h` elapses. Test cooldown.

### Caps and forbidden states

- **AC-92.10.** Global cap: `TODO_SELF_INIT_DAILY_CAP = 3` promotions per self_id per 24h rolling window. Excess matches are deferred, not dropped, and logged. Test at cap + 1.
- **AC-92.11.** An epic (`is_epic = 1`) cannot be marked `completed` while any child is not completed — attempt raises `TodoEpicIncomplete`. Test.
- **AC-92.12.** A child completing does not auto-complete its epic — the epic stays open until explicitly closed. Test.

### Observability

- **AC-92.13.** Prometheus: `turing_todo_ready_matches_total{self_id}`, `turing_todo_self_init_daily{self_id}` (gauge), `turing_todo_cycle_attempts_total`. Test metrics update.
- **AC-92.14.** `stronghold self digest` lists the top 5 ready-and-promotable todos with motivator activation. Test.

### Edge cases

- **AC-92.15.** A todo whose motivator has been archived (self-node deleted) becomes permanently un-ready; reported in digest as "orphaned motivation." Test.
- **AC-92.16.** Mood `focus` below `MOOD_FOCUS_FLOOR = 0.3` suppresses self-initiation that tick (spec 27 hook); the match is deferred, not dropped. Test.

## Implementation

```python
# self_todos/dag.py

TODO_READY_ACTIVATION_FLOOR: float = 0.5
TODO_READY_BATCH: int = 20
TODO_SELF_INIT_DAILY_CAP: int = 3
TODO_REPROMOTE_COOLDOWN: timedelta = timedelta(hours=6)
TODO_DAG_MAX_DEPTH: int = 6


def ready(repo, self_id: str, now: datetime) -> list[ReadyTodo]:
    pending = repo.pending_todos(self_id)
    out = []
    for todo in pending:
        if todo.parent_todo_id:
            parent = repo.get_todo(todo.parent_todo_id)
            if parent.status != "completed":
                continue
        motivator = repo.get_self_node(todo.motivated_by_node_id)
        if motivator is None or motivator.archived:
            continue
        act = activation.active_now(motivator, now)
        if act <= TODO_READY_ACTIVATION_FLOOR:
            continue
        out.append(ReadyTodo(todo=todo, activation=act))
    out.sort(key=lambda r: (-r.activation, r.todo.created_at))
    return out[:TODO_READY_BATCH]


def idle_tick(repo, self_id: str, now: datetime) -> int:
    if _daily_cap_reached(repo, self_id, now):
        return 0
    if _mood_focus_low(repo, self_id, now):
        return 0
    promoted = 0
    for match in ready(repo, self_id, now):
        if _in_cooldown(match.todo, now):
            continue
        prio = 20 + int(10 * (1.0 - match.activation))
        scheduler.submit_motivation(match.todo, priority=prio)
        repo.mark_promoted(match.todo.id, now)
        promoted += 1
        if promoted >= TODO_SELF_INIT_DAILY_CAP:
            break
    return promoted
```

## Open questions

- **Q92.1.** Allow multiple parents per child (true DAG) vs. tree-only? Current spec is single-parent for simplicity; mark as future extension.
- **Q92.2.** Daily cap of 3 — pulled from "won't overwhelm operator." Tune with real operator feedback.
- **Q92.3.** Should `ready()` return a reason code (why a given todo wasn't ready) for debugging? Add in observability spec, not here.
- **Q92.4.** Completion-cascade option: explicit `close-epic --cascade` to auto-close all children. Out of scope for v1.
