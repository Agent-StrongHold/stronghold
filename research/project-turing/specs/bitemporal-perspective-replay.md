# Spec 90 — Bitemporal perspective replay

*Every memory row carries `valid_from`/`valid_to` and every retrieval returns a waypoint trace, enabling "what did I believe on 2026-03-14" queries without destroying history.*

**Depends on:** [schema.md](./schema.md), [persistence.md](./persistence.md), [retrieval.md](./retrieval.md), [activation-graph.md](./activation-graph.md).
**Depended on by:** [trajectory-weighted-promotion.md](./trajectory-weighted-promotion.md) (replays past attributions), [weekly-self-dialogue-ritual.md](./weekly-self-dialogue-ritual.md) (samples across time windows).

---

## Current state

Turing memory rows have `created_at` and are durable once promoted past OPINION (see schema.md + memory-source-state.md). Contradiction resolution today supersedes an old memory by writing a new one and flagging the old as shadowed — but there is no `valid_from`/`valid_to` pair, so time-travel queries ("what weight did this memory carry on date D?") are not answerable and retrieval does not surface the chain of contributors that caused a match.

## Target

Add bitemporal stamps to every memory row and return a **waypoint trace** (ordered list of contributors + retrieval filters that surfaced the row) alongside every retrieval result. Introduce `perspective_at(memory_id, at_datetime)` which reconstructs the memory's weight and contributors as of that datetime. Superseded memories get `valid_to` set instead of being deleted. Existing rows migrate to `valid_from = created_at`, `valid_to = NULL`.

## Acceptance criteria

### Schema

- **AC-90.1.** Add columns to `memories`:
  ```sql
  valid_from  TEXT NOT NULL,
  valid_to    TEXT NULL  -- NULL = currently believed
  ```
  Indexed `(self_id, valid_from, valid_to)`. Test.
- **AC-90.2.** Invariant: `valid_from <= created_at` always. Enforced at write time and by a CHECK constraint where the backend supports one. Test.
- **AC-90.3.** Invariant: `valid_to IS NULL OR valid_to > valid_from`. Test attempted write with reversed pair raises.
- **AC-90.4.** Migration: existing rows get `valid_from = created_at`, `valid_to = NULL`. One-shot migration script idempotent. Test on a fixture snapshot.

### Supersession semantics

- **AC-90.5.** When contradiction-resolution (spec 14) shadows a memory, it sets `valid_to = now()` on the old row and writes the new row with `valid_from = now()`. The old row is **not** soft-deleted. Test both rows exist after supersession.
- **AC-90.6.** Durable-tier rows (LESSON / REGRET / ACCOMPLISHMENT / AFFIRMATION / WISDOM) remain non-deletable; `valid_to` is the only permitted mutation. Test any DELETE attempt against a durable row raises.

### Waypoint trace shape

- **AC-90.7.** Every retrieval result includes a `waypoint` object:
  ```
  {
      retrieval_filters: {query, k, since, tier_mask, ...},
      contributors: [{node_id, origin, weight, rationale}, ...],
      activation_score: float,
      retrieved_at: datetime,
  }
  ```
  `contributors` respects the per-target cap (K≤8) from spec 38. Test.
- **AC-90.8.** Waypoint contributor ordering is descending by `|weight|`; ties broken by `node_id` ascending. Test deterministic order.

### Bitemporal API

- **AC-90.9.** `perspective_at(memory_id, at_datetime) -> PerspectiveView` returns:
  ```
  {
      memory_id, weight_at, contributors_at, tier_at,
      valid_from, valid_to, observed_at: at_datetime,
  }
  ```
  Weight is computed from the activation graph as it stood at `at_datetime` (contributors whose own `valid_from <= at_datetime < valid_to`). Test.
- **AC-90.10.** `perspective_at` called with `at_datetime < valid_from` raises `PerspectiveOutOfRange`. Test.
- **AC-90.11.** `perspective_at(at_datetime = now())` returns the same contributors as a fresh retrieval for that memory. Test round-trip equality within float tolerance (1e-6).

### Retrieval integration

- **AC-90.12.** Standard retrieval surfaces ONLY rows where `valid_to IS NULL OR valid_to > now()`. Historical rows remain reachable only via `perspective_at` or an explicit `as_of=` kwarg. Test shadowed memory is excluded from normal retrieval.
- **AC-90.13.** Explicit `as_of=` on retrieval returns rows where `valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)`. Test.

### Edge cases

- **AC-90.14.** Rapid supersession within the same request (two contradictions in one turn) yields three rows with non-overlapping `[valid_from, valid_to)` intervals. Test interval coverage.
- **AC-90.15.** A memory's waypoint trace excludes contributors whose own `valid_to` is non-NULL at retrieval time — superseded rules don't leak into current traces. Test.

## Implementation

```python
# persistence/bitemporal.py

@dataclass(frozen=True)
class Waypoint:
    retrieval_filters: dict
    contributors: list[Contributor]
    activation_score: float
    retrieved_at: datetime


@dataclass(frozen=True)
class PerspectiveView:
    memory_id: str
    weight_at: float
    contributors_at: list[Contributor]
    tier_at: MemoryTier
    valid_from: datetime
    valid_to: datetime | None
    observed_at: datetime


def supersede(repo, old_id: str, new_memory: Memory, now: datetime) -> None:
    old = repo.get(old_id)
    if old.tier.is_durable():
        # durable rows can only have valid_to set — no other mutation
        repo.set_valid_to(old_id, now)
    else:
        repo.set_valid_to(old_id, now)
    repo.insert(new_memory.with_(valid_from=now, valid_to=None))


def perspective_at(repo, memory_id: str, at: datetime) -> PerspectiveView:
    m = repo.get(memory_id)
    if at < m.valid_from:
        raise PerspectiveOutOfRange(memory_id, at, m.valid_from)
    contribs = repo.contributors_valid_at(memory_id, at)  # respects cap + valid window
    weight = sum(c.weight for c in contribs)
    tier = repo.tier_history(memory_id, at)
    return PerspectiveView(
        memory_id=memory_id, weight_at=weight, contributors_at=contribs,
        tier_at=tier, valid_from=m.valid_from, valid_to=m.valid_to, observed_at=at,
    )
```

## Open questions

- **Q90.1.** Do we want a separate `tier_history` table or reconstruct tier from write-path events? Reconstruction keeps schema lean; a table is faster. Deferred until P90 latency on `perspective_at` is measured.
- **Q90.2.** Waypoint trace grows linearly with K (≤8). Storing every trace is heavy; we return on demand without persisting. Confirm by ADR.
- **Q90.3.** Should `as_of=` kwarg be exposed on the CLI (`stronghold self recall --as-of 2026-03-14`) or only programmatic? Leaning programmatic for v1.
- **Q90.4.** Time-zone handling: all stamps UTC; client converts. Verify retrieval doesn't leak local TZ.
