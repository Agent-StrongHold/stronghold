# Spec 24 — Self-nodes: passions, hobbies, interests, preferences, skills

*The non-personality attributes that accrete from lived experience. Four "what I care about / engage with" kinds (passion, hobby, interest, preference) and one time-dynamic kind (skill).*

**Depends on:** [self-schema.md](./self-schema.md).
**Depended on by:** [activation-graph.md](./activation-graph.md), [self-surface.md](./self-surface.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- Nothing in `main` or on Turing models the self's durable attitudes. Specialist agents may have seed RULES.md files, but there is no persisted, self-owned "what I care about" layer.

## Target

Five node kinds that share a common pattern (self-authored through reflection, stored durably, read into the activation graph) but differ in shape:

| Kind | What it is | Stance vs. activity | Has strength? | Has level? | Has time-dynamic? |
|------|------------|---------------------|---------------|------------|-------------------|
| Passion | A stance about what I care about | Stance | ✓ | — | — |
| Hobby | An activity I engage in | Activity | — | — | `last_engaged_at` only |
| Interest | A topical pull without commitment to practice | Neither | — | — | `last_noticed_at` only |
| Preference | A concrete like/dislike/favorite/avoid | — | ✓ | — | — |
| Skill | Something I can do; decays with time | Activity | — | ✓ | Decay function |

The four non-skill kinds initialize **empty at bootstrap** (per DESIGN.md and [autonoetic-self.md §3.1](../autonoetic-self.md#31-bootstrap)) and accrete via the self's `note_*` tools during reflection. Skills also initialize empty.

## Acceptance criteria

### Creation invariants

- **AC-24.1.** `note_passion(text, strength)` inserts a `Passion` row with `strength ∈ [0.0, 1.0]`, auto-assigned `rank = max(existing_ranks) + 1`, `first_noticed_at = now()`. Out-of-range strength raises. Duplicate text (case-insensitive, whitespace-normalized) raises with a suggestion to use `revise_passion`. Test.
- **AC-24.2.** `note_hobby(name, description)` inserts a `Hobby` with `last_engaged_at = None`. Duplicate name (case-insensitive) raises. Test.
- **AC-24.3.** `note_interest(topic, description)` inserts an `Interest` with `last_noticed_at = None`. Duplicate topic (case-insensitive) raises. Test.
- **AC-24.4.** `note_preference(kind, target, strength, rationale)` inserts a `Preference`. `(self_id, kind, target)` must be unique; collision raises. Test.
- **AC-24.5.** `note_skill(name, level, kind, decay_rate_per_day=None)` inserts a `Skill` with `stored_level=level`, `last_practiced_at=now()`. If `decay_rate_per_day` is omitted, it defaults per `kind`:
  - `intellectual`: 0.0005/day
  - `physical`: 0.005/day
  - `habit`: 0.002/day
  - `social`: 0.001/day

  Out-of-range level raises. Test for each default.

### Mutation invariants

- **AC-24.6.** Passion rank is re-orderable via `rerank_passions(self_id, ordered_ids)`. The call is atomic: either all ranks update or none. A list missing any current passion raises. A list containing a non-existent passion raises. Test.
- **AC-24.7.** `strength` on passions/preferences is mutable via `revise_passion(id, strength=...)` / `revise_preference(id, strength=...)`. Setting `strength = 0.0` is equivalent to soft-archiving — the row remains queryable but does not contribute to the activation graph. Test.
- **AC-24.8.** `last_engaged_at` on a hobby is updated only by `note_engagement(hobby_id, notes)`. The notes are also written as an OBSERVATION-tier memory. Test.
- **AC-24.9.** `last_noticed_at` on an interest is updated by `note_interest_trigger(interest_id, source_memory_id)`. Test.
- **AC-24.10.** `practice_skill(skill_id, new_level=None, notes="")` updates `stored_level` (if provided; else unchanged) and sets `last_practiced_at = now()`. Writes an OBSERVATION-tier memory with the notes. Test.
- **AC-24.11.** No node is deletable by the self. Archival is via setting `strength=0` (passions/preferences) or `last_engaged_at=None, description="[archived]"` convention. Operators can hard-delete at the database layer. Test asserts no self-tool deletes.

### Skill decay

- **AC-24.12.** `current_level(skill, at=now())` returns `stored_level × exp(-decay_rate_per_day × days_since_practice)`. `days_since_practice = (at - last_practiced_at).total_seconds() / 86400`. Test at known inputs (e.g., `level=1.0, rate=0.005, 30 days → ≈0.861`).
- **AC-24.13.** `current_level` is clamped to `[0.0, 1.0]`. A skill that would compute below 0.0 (impossible under the formula, but guard anyway) clamps to 0.0. Test.
- **AC-24.14.** `current_level` is a pure function of stored fields — no DB write, no mutation. Test asserts no persistence side effects.
- **AC-24.15.** `practice_skill` resets `last_practiced_at` and may raise `stored_level` (to recognize improvement through practice) but never lowers it. An attempt to lower `stored_level` via `practice_skill` raises. A separate `downgrade_skill(id, new_level, reason)` exists for explicit downgrade and writes a LESSON-tier memory. Test.
- **AC-24.16.** Skill decay is applied only on read. A scheduled decay job does not exist. Test confirms no such job runs (by checking the Reactor's registered triggers).

### Graph integration

- **AC-24.17.** Every note_* insertion optionally takes `contributes_to: list[(target_node_id, weight)]` so the self can, in one tool call, create the node AND wire it into the activation graph. Weights follow the contributor rules (spec 25). Test.
- **AC-24.18.** Reciprocal contributions (e.g., the new hobby contributing to a facet and the facet contributing to the hobby) require **two** calls, or the convenience `wire_reciprocal(node_a, node_b, a_to_b_weight, b_to_a_weight)` helper. There is no implicit bidirectional wiring. Test.

### Edge cases

- **AC-24.19.** A passion whose `text` is a near-duplicate of an existing one ("I love art" vs. "I care about art") is accepted — exact-match duplicate detection only. The tuning detector (spec 11) flags suspiciously similar passions for potential merge. Test.
- **AC-24.20.** A skill with an unrecognized `kind` not in `SkillKind` raises at construction (enum validation). Test.
- **AC-24.21.** `practice_skill` on a skill that hasn't decayed below `stored_level` still updates `last_practiced_at`. This is intentional — practice is recorded regardless of whether the stored level would drop today. Test.
- **AC-24.22.** Passion rank uniqueness survives reordering, deletion-through-archive, and concurrent `rerank` calls by holding an advisory lock on `self_id` during rerank. Test with simulated concurrent reranks.

## Implementation

### 24.1 Default decay rates

```python
DEFAULT_DECAY_RATES: dict[SkillKind, float] = {
    SkillKind.INTELLECTUAL: 0.0005,
    SkillKind.PHYSICAL:     0.005,
    SkillKind.HABIT:        0.002,
    SkillKind.SOCIAL:       0.001,
}
```

Rationale: physical skills lose the most per idle day (muscle memory), intellectual skills the least (once learned, retrieval stays plausible), habits and social calibration sit between.

### 24.2 Skill decay read-path

```python
import math

def current_level(skill: Skill, at: datetime) -> float:
    days = max(0.0, (at - skill.last_practiced_at).total_seconds() / 86400.0)
    raw = skill.stored_level * math.exp(-skill.decay_rate_per_day * days)
    return max(0.0, min(1.0, raw))
```

### 24.3 Tool signatures

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

def note_skill(self_id: str, name: str, level: float, kind: SkillKind,
               decay_rate_per_day: float | None = None,
               contributes_to: list[tuple[str, float]] | None = None) -> Skill: ...

def practice_skill(self_id: str, skill_id: str,
                   new_level: float | None = None, notes: str = "") -> Skill: ...

def downgrade_skill(self_id: str, skill_id: str,
                    new_level: float, reason: str) -> Skill: ...

def rerank_passions(self_id: str, ordered_ids: list[str]) -> list[Passion]: ...
```

All tool entry points validate `self_id` matches the current self and raise on cross-self writes.

### 24.4 Engagement / notice recording

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

- **Q24.1.** Default decay rates are seeds. Per-deployment calibration (spec 11 tuner) can adjust them based on observed patterns (is a `physical` skill actually decaying faster than an `intellectual` one in this self's real usage?).
- **Q24.2.** Distinction between `interest` and `preference` is sharp in theory (topical pull vs. concrete choice) but may be muddy in LLM-driven authoring. A merge-or-split detector is plausible but deferred.
- **Q24.3.** `contributes_to` in note_* calls couples node-creation and graph-wiring. An alternative is to always separate them (create node, then wire). Coupling is kept for ergonomics; the self can still do it in two steps.
- **Q24.4.** Skill `stored_level` can only go up via `practice_skill`. Realistically, a skill can regress from injury, disuse beyond normal decay, or retraining into something incompatible. `downgrade_skill` handles explicit regression, but the gesture requires naming a reason — might push the self toward narrative honesty, might add friction.
- **Q24.5.** Archival by `strength=0` is a soft delete, which makes querying "my current passions" slightly heavier (filter on `strength > 0`). An explicit `archived: bool` column is clearer but adds another field everywhere. Leaving as `strength=0` convention for now.
