# Spec 24 — Self-nodes: passions, hobbies, interests, preferences

*The non-personality attributes that accrete from lived experience. Four "what I care about / engage with" kinds: passion, hobby, interest, preference.*

**Depends on:** [self-schema.md](./self-schema.md).
**Depended on by:** [activation-graph.md](./activation-graph.md), [self-surface.md](./self-surface.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- Nothing in `main` or on Turing models the self's durable attitudes. Specialist agents may have seed RULES.md files, but there is no persisted, self-owned "what I care about" layer.

## Target

Four node kinds that share a common pattern (self-authored through reflection, stored durably, read into the activation graph) but differ in shape:

| Kind | What it is | Stance vs. activity | Has strength? | Has time-dynamic? |
|------|------------|---------------------|---------------|-------------------|
| Passion | A stance about what I care about | Stance | ✓ | — |
| Hobby | An activity I engage in | Activity | — | `last_engaged_at` only |
| Interest | A topical pull without commitment to practice | Neither | — | `last_noticed_at` only |
| Preference | A concrete like/dislike/favorite/avoid | — | ✓ | — |

The four kinds initialize **empty at bootstrap** (per DESIGN.md and [autonoetic-self.md §3.1](../autonoetic-self.md#31-bootstrap)) and accrete via the self's `note_*` tools during reflection.

## Acceptance criteria

### Creation invariants

- **AC-24.1.** `note_passion(text, strength)` inserts a `Passion` row with `strength ∈ [0.0, 1.0]`, auto-assigned `rank = max(existing_ranks) + 1`, `first_noticed_at = now()`. Out-of-range strength raises. Duplicate text (case-insensitive, whitespace-normalized) raises with a suggestion to use `revise_passion`. Test.
- **AC-24.2.** `note_hobby(name, description)` inserts a `Hobby` with `last_engaged_at = None`. Duplicate name (case-insensitive) raises. Test.
- **AC-24.3.** `note_interest(topic, description)` inserts an `Interest` with `last_noticed_at = None`. Duplicate topic (case-insensitive) raises. Test.
- **AC-24.4.** `note_preference(kind, target, strength, rationale)` inserts a `Preference`. `(self_id, kind, target)` must be unique; collision raises. Test.

### Mutation invariants

- **AC-24.5.** Passion rank is re-orderable via `rerank_passions(self_id, ordered_ids)`. The call is atomic: either all ranks update or none. A list missing any current passion raises. A list containing a non-existent passion raises. Test.
- **AC-24.6.** `strength` on passions/preferences is mutable via `revise_passion(id, strength=...)` / `revise_preference(id, strength=...)`. Setting `strength = 0.0` is equivalent to soft-archiving — the row remains queryable but does not contribute to the activation graph. Test.
- **AC-24.7.** `last_engaged_at` on a hobby is updated only by `note_engagement(hobby_id, notes)`. The notes are also written as an OBSERVATION-tier memory. Test.
- **AC-24.8.** `last_noticed_at` on an interest is updated by `note_interest_trigger(interest_id, source_memory_id)`. Test.
- **AC-24.9.** No node is deletable by the self. Archival is via setting `strength=0` (passions/preferences) or `last_engaged_at=None, description="[archived]"` convention. Operators can hard-delete at the database layer. Test asserts no self-tool deletes.

### Graph integration

- **AC-24.10.** Every note_* insertion optionally takes `contributes_to: list[(target_node_id, weight)]` so the self can, in one tool call, create the node AND wire it into the activation graph. Weights follow the contributor rules (spec 25). Test.
- **AC-24.11.** Reciprocal contributions (e.g., the new hobby contributing to a facet and the facet contributing to the hobby) require **two** calls, or the convenience `wire_reciprocal(node_a, node_b, a_to_b_weight, b_to_a_weight)` helper. There is no implicit bidirectional wiring. Test.

### Edge cases

- **AC-24.12.** A passion whose `text` is a near-duplicate of an existing one ("I love art" vs. "I care about art") is accepted — exact-match duplicate detection only. The tuning detector (spec 11) flags suspiciously similar passions for potential merge. Test.
- **AC-24.13.** Passion rank uniqueness survives reordering, deletion-through-archive, and concurrent `rerank` calls by holding an advisory lock on `self_id` during rerank. Test with simulated concurrent reranks.

## Implementation

### 24.1 Tool signatures

```python
def note_passion(self_id: str, text: str, strength: float,
                 contributes_to: list[tuple[str, float]] | None = None) -> Passion: ...

def note_hobby(self_id: str, name: str, description: str,
               contributes_to: list[tuple[str, float]] | None = None) -> Hobby: ...

def note_interest(self_id: str, topic: str, description: str,
                  contributes_to: list[tuple[str, float]] | None = None) -> Interest: ...

def note_preference(self_id: str, kind: PreferenceKind, target: str,
                    strength: float, rationale: str,
                    contributes_to: list[tuple[str, float]] | None = None) -> Preference: ...

def rerank_passions(self_id: str, ordered_ids: list[str]) -> list[Passion]: ...
```

All tool entry points validate `self_id` matches the current self and raise on cross-self writes.

### 24.2 Engagement / notice recording

```python
def note_engagement(self_id: str, hobby_id: str, notes: str) -> None:
    hobby = repo.get_hobby(self_id, hobby_id)
    hobby.last_engaged_at = datetime.now(UTC)
    hobby.updated_at = datetime.now(UTC)
    repo.update_hobby(hobby)
    memories.write_observation(
        self_id=self_id,
        content=f"[hobby engagement] {hobby.name}: {notes}",
        intent_at_time="engage hobby",
        context={"hobby_id": hobby_id},
    )
```

Identical shape for `note_interest_trigger`.

## Open questions

- **Q24.1.** Distinction between `interest` and `preference` is sharp in theory (topical pull vs. concrete choice) but may be muddy in LLM-driven authoring. A merge-or-split detector is plausible but deferred.
- **Q24.2.** `contributes_to` in note_* calls couples node-creation and graph-wiring. An alternative is to always separate them (create node, then wire). Coupling is kept for ergonomics; the self can still do it in two steps.
- **Q24.3.** Archival by `strength=0` is a soft delete, which makes querying "my current passions" slightly heavier (filter on `strength > 0`). An explicit `archived: bool` column is clearer but adds another field everywhere. Leaving as `strength=0` convention for now.
