# Spec 26 — Self-todos

*The self's own task list. Every todo links to the self-model node that motivates it; revisions are preserved; completions carry an outcome. Active todos surface in every prompt.*

**Depends on:** [self-schema.md](./self-schema.md), [self-nodes.md](./self-nodes.md).
**Depended on by:** [self-surface.md](./self-surface.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- `main` has no self-authored task list. Proactive work on Turing is driven by motivation/backlog items (spec 9), but those are dispatcher items — they don't carry first-person intent.
- The self has no way to say "I want to do X because it serves passion Y" and have that persist across the week.

## Target

A minimal, durable, first-person task list. Every todo has required provenance (which self-node motivates it), is rewriteable with full revision history, and carries a completion outcome when closed. Todos are self-authored only — no one else writes to this table.

## Acceptance criteria

### Creation

- **AC-26.1.** `write_self_todo(text, motivated_by_node_id)` inserts a `SelfTodo` row with `status = ACTIVE`, `created_at = now()`, `outcome_text = None`. Test.
- **AC-26.2.** `motivated_by_node_id` is required. Insertion without it raises. Test.
- **AC-26.3.** `motivated_by_node_id` must reference an existing, non-archived self-model node (passion, hobby, interest, preference, skill, personality_facet). Dangling references raise. Test.
- **AC-26.4.** `text` is capped at 500 characters. Longer text raises with a `TodoTextTooLong` error. Test at 500, 501.
- **AC-26.5.** There is no limit on active todos per self, but the tuning detector (spec 11) flags when count > `TODO_VOLUME_THRESHOLD` (default 50) as a signal of possible thrashing. Flag-only.

### Revision

- **AC-26.6.** `revise_self_todo(id, new_text, reason)` updates `SelfTodo.text` and inserts a `SelfTodoRevision` row with `text_before`, `text_after`, `revised_at`, `revision_num = current_max + 1`. Test asserts both the mutation and the append-only history.
- **AC-26.7.** Revising a `completed` or `archived` todo raises. A completed todo is immutable. Test.
- **AC-26.8.** `revision_num` is monotonic per `todo_id`, starting at 1 on the first revision. A second revision increments. Concurrent revisions are serialized by an advisory lock on `todo_id`. Test.
- **AC-26.9.** `SelfTodoRevision` rows are never updated or deleted by any self-tool. Any attempted mutation raises `ImmutableRevisionRow`. Test.
- **AC-26.10.** `motivated_by_node_id` is **not** revisable — if the motivation has changed, the self should archive the todo and write a new one. A `change_motivation(todo_id, new_node_id)` tool does not exist. Test.

### Completion

- **AC-26.11.** `complete_self_todo(id, outcome_text)` sets `status = COMPLETED`, `outcome_text = outcome_text`, `updated_at = now()`. `outcome_text` is required and non-empty. Empty or missing raises. Test.
- **AC-26.12.** Completion also writes an AFFIRMATION-tier episodic memory (per write-paths.md) with:
  - `content = f"[todo completed] {text} → {outcome_text}"`
  - `intent_at_time = "complete self todo"`
  - `context = {"todo_id": id, "motivated_by": motivated_by_node_id}`
  - `source = I_DID`
  Test asserts the memory is written with the right tier and source.
- **AC-26.13.** Completing an already-completed or archived todo raises `TodoNotActive`. Test.
- **AC-26.14.** Completion writes a contributor edge from the motivating node back to the completed-todo-memory with `weight = +0.3` (reinforces the motivating node by evidence-of-action). `origin = self`, `rationale = "todo completion"`. Test.

### Archival

- **AC-26.15.** `archive_self_todo(id, reason)` sets `status = ARCHIVED`, `updated_at = now()`. `reason` is stored as an OBSERVATION memory but NOT as `outcome_text` (archived ≠ completed). Test.
- **AC-26.16.** Archiving an already-completed todo raises. A completed todo stays completed forever. Test.
- **AC-26.17.** Archived todos are hidden from the minimal prompt block (spec 28) but still retrievable via `recall_self()` with `include_archived=True`. Test.

### Query

- **AC-26.18.** `list_active_todos(self_id)` returns all todos with `status = ACTIVE`, ordered by `created_at` ascending. Test.
- **AC-26.19.** `list_todos_for_motivator(motivator_node_id, include_archived=False)` returns all todos motivated by that node. Test.
- **AC-26.20.** `recall_self()` includes the top-N active todos in its structured output (spec 28 AC-28.x). Default N=10.

### Edge cases

- **AC-26.21.** A todo whose motivating node is later archived (passion `strength=0` or similar) stays live but is flagged in `list_active_todos` with a `motivator_state = "archived"` annotation. The self may then archive the todo or revise its motivation (by archiving and re-writing). Test.
- **AC-26.22.** A concurrent `complete` and `revise` on the same todo is serialized by the advisory lock; whichever wins the lock completes first. If `complete` wins, the subsequent `revise` raises `TodoNotActive`. Test.
- **AC-26.23.** A todo text containing personally-identifying-information-shaped content (emails, phone numbers) is NOT rejected — the self is allowed to write what it wants about itself. The Warden scans outputs, not the self's internal writes. Documented as intentional.
- **AC-26.24.** Resurrecting an archived todo requires writing a new todo; there is no `unarchive`. Test asserts no such tool exists.

## Implementation

### 26.1 Tool signatures

```python
def write_self_todo(
    self_id: str,
    text: str,
    motivated_by_node_id: str,
) -> SelfTodo: ...

def revise_self_todo(
    self_id: str,
    todo_id: str,
    new_text: str,
    reason: str,
) -> SelfTodo: ...

def complete_self_todo(
    self_id: str,
    todo_id: str,
    outcome_text: str,
) -> SelfTodo: ...

def archive_self_todo(
    self_id: str,
    todo_id: str,
    reason: str,
) -> SelfTodo: ...

def list_active_todos(self_id: str) -> list[SelfTodo]: ...
def list_todos_for_motivator(self_id: str, motivator_id: str,
                              include_archived: bool = False) -> list[SelfTodo]: ...
```

### 26.2 Revision append

```python
def revise_self_todo(self_id, todo_id, new_text, reason):
    with repo.advisory_lock(f"todo:{todo_id}"):
        todo = repo.get_todo(todo_id)
        if todo.status != TodoStatus.ACTIVE:
            raise TodoNotActive(todo_id)
        if len(new_text) > 500:
            raise TodoTextTooLong()
        before = todo.text
        todo.text = new_text
        todo.updated_at = now()
        repo.update_todo(todo)
        last = repo.max_revision_num(todo_id) or 0
        repo.insert_todo_revision(SelfTodoRevision(
            node_id=new_id("rev"),
            self_id=self_id,
            todo_id=todo_id,
            revision_num=last + 1,
            text_before=before,
            text_after=new_text,
            revised_at=now(),
        ))
        memories.write_observation(
            self_id=self_id,
            content=f"[todo revised] {before} → {new_text} (reason: {reason})",
            intent_at_time="revise self todo",
            context={"todo_id": todo_id},
        )
        return todo
```

### 26.3 Completion reinforcement edge

```python
def complete_self_todo(self_id, todo_id, outcome_text):
    with repo.advisory_lock(f"todo:{todo_id}"):
        todo = repo.get_todo(todo_id)
        if todo.status != TodoStatus.ACTIVE:
            raise TodoNotActive(todo_id)
        if not outcome_text.strip():
            raise ValueError("outcome_text is required on completion")
        todo.status = TodoStatus.COMPLETED
        todo.outcome_text = outcome_text
        todo.updated_at = now()
        repo.update_todo(todo)

        mem = memories.write_affirmation(
            self_id=self_id,
            content=f"[todo completed] {todo.text} → {outcome_text}",
            intent_at_time="complete self todo",
            context={"todo_id": todo_id, "motivated_by": todo.motivated_by_node_id},
        )
        repo.insert_contributor(ActivationContributor(
            node_id=new_id("ctr"),
            self_id=self_id,
            target_node_id=todo.motivated_by_node_id,
            target_kind=repo.kind_of(todo.motivated_by_node_id),
            source_id=mem.memory_id,
            source_kind="memory",
            weight=0.3,
            origin=ContributorOrigin.SELF,
            rationale="todo completion reinforces motivator",
        ))
        return todo
```

### 26.4 Minimal block placement

Active todos in the minimal prompt block appear as:

```
Active todos (3):
 - [todo:42] Re-read Tulving '85 (motivated by passion:3)
 - [todo:51] Practice embedding-index tests (motivated by skill:embeddings)
 - [todo:77] Write a note about last week's retest shift (motivated by facet:openness.inquisitiveness)
```

IDs are included so the self can reference them directly in subsequent tool calls.

## Open questions

- **Q26.1.** `text` cap of 500 is a seed. HEXACO retest justifications are capped at 200 (spec 23), and general memories aren't capped. 500 is a rough "enough to name the task, not enough to encode an essay" target. Tunable.
- **Q26.2.** Immutable `motivated_by_node_id` forces the self to archive-and-rewrite rather than edit in place. This is slightly more paperwork but makes motivation changes structurally visible in the todo history. Alternative: allow `change_motivation` and log the change as a revision. Deferred.
- **Q26.3.** Completion → contributor edge at weight `+0.3` is a seed. Tuning detector can adjust whether todo completions meaningfully reinforce their motivators over time. If the coefficient drifts toward zero, the self isn't learning from its own task completions, which is worth flagging.
- **Q26.4.** Revision history could grow large for todos the self repeatedly rewrites. A compaction pass (keep first, last, and every 10th) is plausible but deferred.
- **Q26.5.** No `snooze_todo(id, until)` facility is specced here. Motivation-dispatcher (spec 9) already handles "when do I act on this?" via pressure and fit. Adding a self-authored snooze would be parallel machinery; deferred.
