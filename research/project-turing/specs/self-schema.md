# Spec 22 — Self-model schema

*Tables and value types for the durable self-model nodes: personality, passions, hobbies, interests, preferences, skills, todos, mood, and the activation-graph edges that relate them.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md).
**Depended on by:** [personality.md](./personality.md), [self-nodes.md](./self-nodes.md), [activation-graph.md](./activation-graph.md), [self-todos.md](./self-todos.md), [mood.md](./mood.md), [self-surface.md](./self-surface.md), [self-bootstrap.md](./self-bootstrap.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- `EpisodicMemory` (spec 1) carries the memory layer. No tables exist for persistent self-model nodes — personality, passions, hobbies, interests, preferences, skills, todos, mood.
- `self_id` is minted (spec 8) but no state is indexed to it beyond memory.
- The Conduit treats every request as a fresh classification; there is no durable "what I am" it consults.

## Target

Add per-`self_id` tables that hold the self's durable attributes alongside episodic memory. Every row is owned by exactly one `self_id`. The research branch runs with one self, so `self_id` is effectively a constant — but the column is present so the schema can later be read by audits that compare selves across deployments.

Every node kind shares four common fields: `node_id`, `self_id`, `created_at`, `updated_at`. Specific node kinds layer their own fields on top.

## Acceptance criteria

### Node identity and ownership

- **AC-22.1.** Every self-model row has a `node_id` that is unique within its table and a `self_id` that matches the owning self. Inserting a row without `self_id` raises. Test.
- **AC-22.2.** `NodeKind` is an enum over `{personality_facet, passion, hobby, interest, preference, skill, todo, mood}`. Used as `source_kind` and `target_kind` in the activation graph (spec 25). Test for every enum member.
- **AC-22.3.** `node_id` values are prefixed by node kind (`facet:honesty_humility.sincerity`, `passion:42`, `skill:python`, ...) so the graph can resolve kind without a join. Regex-based validation test on insert.

### Personality tables

- **AC-22.4.** `self_personality_facets` has exactly 24 rows per `self_id`: one per HEXACO facet. A 25th insert raises. A 23-row state is invalid and fails the bootstrap completion check (spec 29). Test.
- **AC-22.5.** Each facet row carries `trait_id` ∈ `{honesty_humility, emotionality, extraversion, agreeableness, conscientiousness, openness}`, `facet_id` (the 4-per-trait slug), `score ∈ [1.0, 5.0]`, `last_revised_at`. Out-of-range score raises. Test.
- **AC-22.6.** `self_personality_items` stores the HEXACO-200 item bank. Static after seed — inserting during normal operation raises. Test that the table has exactly 200 rows after seed.
- **AC-22.7.** `self_personality_answers` rows carry `item_id`, `revision_id` (nullable for bootstrap answers), `answer_1_5 ∈ {1,2,3,4,5}`, `justification_text`, `asked_at`. Out-of-range answer raises. Test.
- **AC-22.8.** `self_personality_revisions` rows carry `revision_id`, `ran_at`, `sampled_item_ids: list[str]` (length 20), `deltas_by_facet: dict[facet_id, float]`. An empty sample or a sample of wrong length raises. Test.

### Simple-node tables

- **AC-22.9.** `self_passions` rows: `text`, `strength ∈ [0.0, 1.0]`, `rank ∈ int≥0` (for primacy ordering, unique within `self_id`), `first_noticed_at`. Out-of-range strength raises. Duplicate rank within the same `self_id` raises. Test.
- **AC-22.10.** `self_hobbies` rows: `name`, `description`, `last_engaged_at` (nullable). No strength field — hobbies don't carry intrinsic weight; their activation is derived from the graph. Test.
- **AC-22.11.** `self_interests` rows: `topic`, `description`, `last_noticed_at`. No strength field; same rationale as hobbies. Test.
- **AC-22.12.** `self_preferences` rows: `kind ∈ {like, dislike, favorite, avoid}`, `target: str`, `strength ∈ [0.0, 1.0]`, `rationale`. `(self_id, kind, target)` is unique. Duplicate insert raises. Test.

### Skills

- **AC-22.13.** `self_skills` rows: `name`, `kind ∈ {intellectual, physical, habit, social}`, `stored_level ∈ [0.0, 1.0]`, `decay_rate_per_day > 0.0`, `last_practiced_at`. Out-of-range level raises. Non-positive decay rate raises. Test.
- **AC-22.14.** `stored_level` is never mutated by decay. Decay is a read-time transformation (spec 24 §4). A write that mutates `stored_level` must set `last_practiced_at = now()` in the same transaction. Test.

### Todos

- **AC-22.15.** `self_todos` rows: `text`, `motivated_by_node_id` (required, foreign-key-like reference into any self-model table), `status ∈ {active, completed, archived}`, `outcome_text` (nullable; required iff status = completed), `created_at`. Insert without `motivated_by_node_id` raises. Marking `completed` without `outcome_text` raises. Test.
- **AC-22.16.** `self_todo_revisions` rows: `todo_id`, `revision_num` (monotonic per todo), `text_before`, `text_after`, `revised_at`. Append-only — updating or deleting a revision row raises. Test.

### Mood

- **AC-22.17.** `self_mood` has exactly one row per `self_id` at any time (singleton state). A second insert raises; updates mutate the existing row. Test.
- **AC-22.18.** Mood row carries `valence ∈ [-1.0, 1.0]`, `arousal ∈ [0.0, 1.0]`, `focus ∈ [0.0, 1.0]`, `last_tick_at`. Out-of-range values raise. Test.

### Activation-graph table

- **AC-22.19.** `self_activation_contributors` rows: `target_node_id`, `target_kind: NodeKind`, `source_id` (node_id, memory_id, or rule_id), `source_kind ∈ NodeKind ∪ {memory, rule, retrieval}`, `weight ∈ [-1.0, 1.0]` (negative allowed for inhibitory edges), `origin ∈ {self, rule, retrieval}`, `rationale: str`, `created_at`. Out-of-range weight raises. Test.
- **AC-22.20.** A contributor where `target_node_id == source_id` raises (no direct self-loops). Test.
- **AC-22.21.** `origin = retrieval` rows carry an `expires_at` timestamp. All other origins carry `expires_at = NULL` (durable). Test.

### Cross-cutting invariants

- **AC-22.22.** Every table has `created_at` and `updated_at` in UTC. Updates that don't touch `updated_at` raise (enforced by the repo layer). Test.
- **AC-22.23.** No self-model table is deletable by the LLM. Only the operator can hard-delete a row; the self can only mark `status=archived` on todos or set `strength=0` on passions/preferences. Test.

## Implementation

### 22.1 Enums

```python
from enum import StrEnum

class Trait(StrEnum):
    HONESTY_HUMILITY = "honesty_humility"
    EMOTIONALITY = "emotionality"
    EXTRAVERSION = "extraversion"
    AGREEABLENESS = "agreeableness"
    CONSCIENTIOUSNESS = "conscientiousness"
    OPENNESS = "openness"


class NodeKind(StrEnum):
    PERSONALITY_FACET = "personality_facet"
    PASSION = "passion"
    HOBBY = "hobby"
    INTEREST = "interest"
    PREFERENCE = "preference"
    SKILL = "skill"
    TODO = "todo"
    MOOD = "mood"


class ContributorOrigin(StrEnum):
    SELF = "self"           # self-authored via write_contributor tool
    RULE = "rule"           # always-on default rule
    RETRIEVAL = "retrieval" # ephemeral per-request semantic match


class SkillKind(StrEnum):
    INTELLECTUAL = "intellectual"
    PHYSICAL = "physical"
    HABIT = "habit"
    SOCIAL = "social"


class PreferenceKind(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"
    FAVORITE = "favorite"
    AVOID = "avoid"


class TodoStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"
```

### 22.2 Common base

```python
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SelfNode:
    node_id: str
    self_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

### 22.3 Personality

```python
@dataclass
class PersonalityFacet(SelfNode):
    trait: Trait
    facet_id: str                     # e.g. "sincerity", "fairness", …
    score: float                      # [1.0, 5.0]
    last_revised_at: datetime

    def __post_init__(self) -> None:
        if not 1.0 <= self.score <= 5.0:
            raise ValueError(f"facet score out of range: {self.score}")


@dataclass
class PersonalityItem(SelfNode):
    item_number: int                  # 1..200
    prompt_text: str
    keyed_facet: str
    reverse_scored: bool


@dataclass
class PersonalityAnswer(SelfNode):
    item_id: str
    revision_id: str | None           # None for bootstrap answers
    answer_1_5: int
    justification_text: str
    asked_at: datetime

    def __post_init__(self) -> None:
        if self.answer_1_5 not in (1, 2, 3, 4, 5):
            raise ValueError("answer must be 1..5")


@dataclass
class PersonalityRevision(SelfNode):
    revision_id: str
    ran_at: datetime
    sampled_item_ids: list[str]       # length exactly 20
    deltas_by_facet: dict[str, float]

    def __post_init__(self) -> None:
        if len(self.sampled_item_ids) != 20:
            raise ValueError("retest sample must be exactly 20 items")
```

### 22.4 Simple nodes

```python
@dataclass
class Passion(SelfNode):
    text: str
    strength: float                   # [0.0, 1.0]
    rank: int                         # unique per self_id
    first_noticed_at: datetime


@dataclass
class Hobby(SelfNode):
    name: str
    description: str
    last_engaged_at: datetime | None = None


@dataclass
class Interest(SelfNode):
    topic: str
    description: str
    last_noticed_at: datetime | None = None


@dataclass
class Preference(SelfNode):
    kind: PreferenceKind
    target: str
    strength: float                   # [0.0, 1.0]
    rationale: str
```

### 22.5 Skills

```python
@dataclass
class Skill(SelfNode):
    name: str
    kind: SkillKind
    stored_level: float               # [0.0, 1.0]; never decayed on disk
    decay_rate_per_day: float         # > 0.0
    last_practiced_at: datetime
```

### 22.6 Todos

```python
@dataclass
class SelfTodo(SelfNode):
    text: str
    motivated_by_node_id: str         # required
    status: TodoStatus = TodoStatus.ACTIVE
    outcome_text: str | None = None


@dataclass
class SelfTodoRevision(SelfNode):
    todo_id: str
    revision_num: int
    text_before: str
    text_after: str
    revised_at: datetime
```

### 22.7 Mood

```python
@dataclass
class Mood(SelfNode):
    valence: float                    # [-1.0, 1.0]
    arousal: float                    # [0.0, 1.0]
    focus: float                      # [0.0, 1.0]
    last_tick_at: datetime
```

### 22.8 Activation graph

```python
@dataclass
class ActivationContributor(SelfNode):
    target_node_id: str
    target_kind: NodeKind
    source_id: str
    source_kind: str                  # NodeKind ∪ {"memory", "rule", "retrieval"}
    weight: float                     # [-1.0, 1.0]
    origin: ContributorOrigin
    rationale: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.target_node_id == self.source_id:
            raise ValueError("contributor cannot target itself")
        if not -1.0 <= self.weight <= 1.0:
            raise ValueError("contributor weight out of range")
        if (self.origin == ContributorOrigin.RETRIEVAL) != (self.expires_at is not None):
            raise ValueError("retrieval contributors must set expires_at; others must not")
```

### 22.9 Schema SQL sketch

```sql
-- All tables are CREATE TABLE IF NOT EXISTS. self_id is a foreign key
-- into the identity table minted in spec 8.

CREATE TABLE self_personality_facets (
    node_id          TEXT PRIMARY KEY,
    self_id          TEXT NOT NULL,
    trait            TEXT NOT NULL,
    facet_id         TEXT NOT NULL,
    score            REAL NOT NULL CHECK (score >= 1.0 AND score <= 5.0),
    last_revised_at  TIMESTAMPTZ NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (self_id, trait, facet_id)
);

-- Analogous tables for: self_personality_items, self_personality_answers,
-- self_personality_revisions, self_passions, self_hobbies, self_interests,
-- self_preferences, self_skills, self_todos, self_todo_revisions, self_mood,
-- self_activation_contributors.

CREATE TABLE self_mood (
    self_id          TEXT PRIMARY KEY,
    valence          REAL NOT NULL CHECK (valence >= -1.0 AND valence <= 1.0),
    arousal          REAL NOT NULL CHECK (arousal >= 0.0 AND arousal <= 1.0),
    focus            REAL NOT NULL CHECK (focus >= 0.0 AND focus <= 1.0),
    last_tick_at     TIMESTAMPTZ NOT NULL,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE self_activation_contributors (
    node_id          TEXT PRIMARY KEY,
    self_id          TEXT NOT NULL,
    target_node_id   TEXT NOT NULL,
    target_kind      TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    source_kind      TEXT NOT NULL,
    weight           REAL NOT NULL CHECK (weight >= -1.0 AND weight <= 1.0),
    origin           TEXT NOT NULL,
    rationale        TEXT NOT NULL,
    expires_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (target_node_id <> source_id),
    CHECK ((origin = 'retrieval') = (expires_at IS NOT NULL))
);
```

## Open questions

- **Q22.1.** `strength` on passions/preferences is `[0.0, 1.0]` while personality `score` is `[1.0, 5.0]`. Two different scales across self-model nodes is a correctness hazard during graph computation (spec 25). Either normalize on read or standardize at schema time. Leaving them as-is for now because HEXACO's Likert-1-to-5 is a load-bearing property for retest maths; the activation graph normalizes on read.
- **Q22.2.** `motivated_by_node_id` is stored as a plain string reference. Actual foreign-key constraints are hard when the target can live in eight tables. Enforcement is at the application layer. Consider a polymorphic-association column pair `(target_table, target_id)` instead.
- **Q22.3.** `self_personality_items` being read-only after seed is an invariant enforced at the application layer. A migration path for a revised HEXACO item bank (new translation, new validated form) isn't defined.
