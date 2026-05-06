# Spec 57 — Bi-temporal validity for memory facts

*Adds `valid_from` / `valid_to` columns to memory rows. Distinct from `created_at` (transaction time): the Conduit learns *when* a fact was true in the world separately from *when* it learned the fact. Permitted only on tiers that model external entities; rejected on self-implicating tiers.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [persistence.md](./persistence.md).
**Depended on by:** [as-of-retrieval.md](./as-of-retrieval.md), [source-identity-and-reliability.md](./source-identity-and-reliability.md), [regret-severity-and-load-bearing.md](./regret-severity-and-load-bearing.md).

---

## Current state

`EpisodicMemory` (spec 1) carries `created_at` and `last_accessed_at`. The supersedes / superseded_by chain (spec 1, spec 4) captures *learning history* — when one belief was supplanted by a later one. The model has no representation of *world time*: when a fact was actually true.

This is fine for self-implicating tiers (REGRET, ACCOMPLISHMENT, AFFIRMATION, WISDOM) — the Conduit's stance is timeless relative to ordinary world events. It is not fine for OBSERVATION and HYPOTHESIS memories about external entities. "Alice worked at OpenAI from January 2024 through June 2025" cannot be expressed today; it can only be expressed as "I learned in March 2026 that Alice worked at OpenAI" with the dates buried inside `content`. That makes time-aware retrieval and time-aware contradiction detection structurally impossible.

## Target

Add two nullable columns to memory: `valid_from: datetime | None` and `valid_to: datetime | None`. Both default `None`.

Semantics:

- `valid_from = None`, `valid_to = None` — fact has no world-time scope; the only time that matters is `created_at`. This is the only legal shape for self-implicating tiers.
- `valid_from` set, `valid_to = None` — fact began at `valid_from` and is still valid as far as the Conduit knows.
- `valid_from` set, `valid_to` set — fact had a known beginning and end in the world.
- `valid_from = None`, `valid_to` set — fact has a known end but unknown beginning. Permitted; common when the Conduit learns that a state has *ended* without knowing when it started.

`valid_to` and `superseded_by` are independent. A fact may have a known world-end (`valid_to` set) and not yet be superseded (no later belief has replaced it). A fact may be superseded (later belief contradicts it) and have `valid_to = None` if the world-end was never directly known.

## Acceptance criteria

- **AC-57.1.** `EpisodicMemory` carries `valid_from: datetime | None = None` and `valid_to: datetime | None = None`. Default-None construction is permitted on every tier. Test.
- **AC-57.2.** When both are set, `valid_to >= valid_from`. Construction with `valid_to < valid_from` raises `ValueError` in `__post_init__`. Negative test.
- **AC-57.3.** `valid_from > now() + 7 days` raises. The Conduit does not record world-tense facts about the far future; future commitments use AFFIRMATION + scheduling. Test.
- **AC-57.4.** Self-implicating tiers (REGRET, ACCOMPLISHMENT, AFFIRMATION, WISDOM) reject any non-None `valid_from` or `valid_to` at construction. Negative test per tier.
- **AC-57.5.** OBSERVATION, HYPOTHESIS, OPINION, LESSON may set either or both. Test per tier.
- **AC-57.6.** `valid_to` is mutable post-construction (the world-end may be learned later). `valid_from` is write-once — mutating it after construction raises. Test both paths.
- **AC-57.7.** Supersession write-path extension: when spec 4 / `detectors/contradiction.md` mints a successor, the predecessor's `valid_to` is set to the successor's `valid_from` *if and only if* the predecessor's `valid_to` was previously `None` and the successor has `valid_from` set. If the predecessor already had `valid_to`, leave it — the world-end was already known and the supersession is a different event. Test both branches.
- **AC-57.8.** Schema migration adds the two columns to `episodic_memory` and `durable_memory` (spec 8). Existing rows backfill with `NULL`. Composite index `(valid_from, valid_to)` created. Migration is reversible. Test UP/DOWN.
- **AC-57.9.** Property test: any random sequence of (insert, mutate-valid_to, supersede) operations produces rows where `valid_from <= valid_to` whenever both are set, no `valid_from` mutates after construction, and predecessor `valid_to` is set on supersession only when both conditions in AC-57.7 hold.

## Implementation

```python
# schema.py — additions to EpisodicMemory

from datetime import UTC, datetime, timedelta

FUTURE_VALID_FROM_BUFFER = timedelta(days=7)

_SELF_IMPLICATING_TIERS = frozenset({
    MemoryTier.REGRET,
    MemoryTier.ACCOMPLISHMENT,
    MemoryTier.AFFIRMATION,
    MemoryTier.WISDOM,
})


@dataclass(frozen=False)
class EpisodicMemory:
    ...
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        ...
        if self.tier in _SELF_IMPLICATING_TIERS:
            if self.valid_from is not None or self.valid_to is not None:
                raise ValueError(f"valid_* not permitted on tier {self.tier}")
        if self.valid_from is not None and self.valid_to is not None:
            if self.valid_to < self.valid_from:
                raise ValueError("valid_to precedes valid_from")
        if self.valid_from is not None:
            if self.valid_from > datetime.now(UTC) + FUTURE_VALID_FROM_BUFFER:
                raise ValueError("valid_from too far in future")
```

`valid_from` write-once enforcement is the same `__setattr__` mechanism spec 1 uses for `immutable`.

Migration:

```sql
ALTER TABLE episodic_memory ADD COLUMN valid_from TIMESTAMP;
ALTER TABLE episodic_memory ADD COLUMN valid_to   TIMESTAMP;
ALTER TABLE durable_memory  ADD COLUMN valid_from TIMESTAMP;
ALTER TABLE durable_memory  ADD COLUMN valid_to   TIMESTAMP;
CREATE INDEX idx_em_valid_window ON episodic_memory(valid_from, valid_to);
CREATE INDEX idx_dm_valid_window ON durable_memory(valid_from, valid_to);
```

Supersession extension to spec 4:

```python
# write-paths.py — inside the REGRET / supersession path

def _maybe_set_predecessor_valid_to(
    predecessor: EpisodicMemory,
    successor: EpisodicMemory,
    repo: Repo,
) -> None:
    if predecessor.valid_to is not None:
        return  # world-end already known; do not overwrite
    if successor.valid_from is None:
        return  # successor has no world-time anchor
    repo.set_valid_to(predecessor.memory_id, successor.valid_from)
```

## Open questions

- **Q57.1.** When the predecessor already has `valid_to` and a supersession event arrives, the spec keeps the original. Reviewer call: alternative is to record the conflict (`context.valid_to_conflict = successor.memory_id`) for later inspection. Cheap to add; defer until a real case is observed.
- **Q57.2.** Time zones: all stored as UTC. Ingestion (spec 4 / write-paths) is responsible for converting incoming local-time claims. Vague claims ("since college") are stored with `valid_from = None` rather than guessed; the resolver may upgrade later.
- **Q57.3.** A long-running fact like "Alice works at OpenAI" arriving at `t1` followed by "Alice works at Anthropic" at `t2` with no `valid_from` produces an inferred `valid_to = t2` on the first row. The actual job change happened somewhere in `[t1, t2]` and the stored value is the upper bound. A future spec could mark this as inferred via a `context.valid_to_inferred = True` flag; deferred until a property test reveals the cost.
- **Q57.4.** Graph-walk over `(entity, predicate)` validity windows benefits from native graph traversal at depth. Deferred to graph-DB integration research — see Stronghold issue #1233.
