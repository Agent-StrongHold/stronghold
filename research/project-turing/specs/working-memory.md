# Spec 14 — Working memory + operator base prompt

*Two clearly-separated prompt regions: an immutable operator-controlled base, and a bounded self-controlled scratch space the self maintains via a periodic reflection loop.*

**Depends on:** [schema.md](./schema.md), [persistence.md](./persistence.md), [motivation.md](./motivation.md).
**Depended on by:** [chat-surface.md](./chat-surface.md), [rss-thinking.md](./rss-thinking.md).

---

## Current state

Built; no spec. The behavior, capacity bounds, JSON update protocol, and base-prompt layering all live in code only.

## Target

A two-layer prompt composition rule that holds for every chat reply, every dream-prompt, every daydream-prompt, every RSS-thinking-prompt: the operator's base prompt (immutable to the self) at the top, the self's working memory (mutable by the self only) immediately after.

Both regions appear in every reasoning prompt. Neither can be edited from the wrong side.

## Acceptance criteria

### Storage shape

- **AC-14.1.** A `working_memory` table holds rows `(entry_id, self_id, content, priority, created_at, updated_at)`. `priority ∈ [0.0, 1.0]`. Test asserts schema.
- **AC-14.2.** `WorkingMemory.entries(self_id)` returns rows ordered by `(priority DESC, created_at ASC)` — high priority first; within the same priority, older first. Test.
- **AC-14.3.** Two distinct `self_id`s see disjoint working-memory rows. Test asserts isolation.

### Capacity bounds

- **AC-14.4.** `WORKING_MEMORY_MAX_ENTRIES` (default 10) is enforced on insert. Over-capacity inserts trigger eviction of `(lowest priority, then oldest created_at)` entries until at-or-below capacity. Test asserts eviction order.
- **AC-14.5.** `WORKING_MEMORY_MAX_CONTENT_LEN` (default 300 chars) truncates content on insert. Test.
- **AC-14.6.** Empty content is rejected (`ValueError`). Test.
- **AC-14.7.** Priority outside `[0.0, 1.0]` is rejected on insert *and* update. Test.

### Self-edit loop

- **AC-14.8.** A `WorkingMemoryMaintenance` producer submits a P13 RASO candidate every `WM_MAINTENANCE_TICKS` (default 12,000 = 2 min at 100Hz). Test asserts cadence.
- **AC-14.9.** When dispatched, the loop reads (a) current WM, (b) durable memories from the last hour, and asks the chat-role provider for a JSON `{"add": [{"content", "priority"}, ...], "remove": ["entry_id", ...]}`. Test asserts the prompt structure.
- **AC-14.10.** Adds and removes from the LLM reply are applied. Removes referencing nonexistent entry_ids are silently ignored (logged). Test.
- **AC-14.11.** Malformed JSON, missing fields, or wrong-shape replies are silently no-op (the WM stays). The maintenance loop never crashes the runtime. Test with several malformed shapes.
- **AC-14.12.** Priorities returned by the LLM are clamped to `[0.0, 1.0]`. Test.

### Operator base prompt

- **AC-14.13.** `--base-prompt <path>` (or `TURING_BASE_PROMPT_PATH` env) loads a markdown file at startup. The file's content is the operator's framing. Test asserts loading.
- **AC-14.14.** When the path is missing or unreadable, the runtime falls back to `DEFAULT_BASE_PROMPT` (a hardcoded constant) with a `WARNING` log. Test.
- **AC-14.15.** The base prompt is read once at startup. Mid-run edits to the file have no effect until restart. Documented behavior. Test asserts the cached value doesn't change after file mutation.
- **AC-14.16.** No write path from the runtime mutates the base-prompt file. Test asserts the file's mtime is unchanged across a smoke run.

### Prompt composition

- **AC-14.17.** Every chat-reply prompt includes both regions, in this exact order, with these exact section headings:

  ```
  ## Base framing (operator-set)
  {base_prompt}

  ## Your working memory (self-maintained)
  {wm.render(self_id)}
  ```

  Test asserts both headings present, in order, and that base_prompt content appears first.
- **AC-14.18.** Daydream, dream, RSS-thinking, and WM-maintenance prompts can opt into including the base + WM regions; default for those (research-mode) is to include them so the self speaks consistently across all reasoning paths. Test asserts opt-in works for at least one path.

### Operator visibility

- **AC-14.19.** `python -m turing.runtime.inspect --db <db> working-memory` prints the current WM entries with priority and created_at. Test asserts CLI output.
- **AC-14.20.** No CLI subcommand mutates working memory (no `set`, `clear`, `add`, `remove`). The self is the only writer. Test asserts the subcommand is read-only by inspecting the `inspect` parser.

## Implementation

### 14.1 Eviction

```python
def _evict_over_capacity(self, self_id, max_entries):
    overflow = self._count(self_id) - max_entries
    if overflow > 0:
        rows = SELECT entry_id ORDER BY priority ASC, created_at ASC LIMIT overflow
        DELETE WHERE entry_id IN rows
```

### 14.2 Maintenance prompt

```
You are Project Turing, maintaining your own working memory.
Working memory is your scratch space — what you want to keep
front-of-mind across conversations and routings. Be selective.

## Current working memory
- [id:abc priority:0.80] focus on the Q4 wiki overhaul
- ...

## Recent durable memories (last hour)
- [accomplishment] resolved the conflicting AFFIRMATIONs
- ...

Return a single JSON object matching this schema exactly:
  {"add": [{"content": "<string>", "priority": <0..1>}, ...],
   "remove": ["<entry_id>", ...]}
Keep the total entries under 10. Only respond with the JSON.
```

### 14.3 Configuration constants

```python
WORKING_MEMORY_MAX_ENTRIES:    int = 10
WORKING_MEMORY_MAX_CONTENT_LEN: int = 300
WM_MAINTENANCE_TICKS:          int = 12_000   # 2 min at 100Hz
```

All tunable via CoefficientTable.

## Open questions

- **Q14.1.** Should WM entries have tags / categories? Currently flat. A category dim could let the chat dispatcher show only relevant entries (e.g., only "current focus" tagged ones, not "user reminder" tagged ones). Deferred until we see real usage patterns.
- **Q14.2.** Time decay: should priority decrease over time if not reinforced (similar to non-durable tier weights)? Currently no — only LLM-driven re-prioritization. Open.
- **Q14.3.** Cross-pool WM: with the per-user session-tag model, do users see "the same" WM, or should WM-entries be tagged with the user that prompted them? Currently shared. May want to revisit if users start writing things into WM that confuse other users' chats.
- **Q14.4.** Operator override pathway: in research mode, sometimes the operator legitimately wants to seed WM with "remember today is a holiday." We've explicitly said no. Workaround: edit base_prompt.md and restart. Acceptable for research.
