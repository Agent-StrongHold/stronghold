# Spec 60 — Regret severity and load-bearing-fact cascade

*Extends `write-paths.md`. REGRET weight scales by hold-duration and downstream-citation count of the superseded fact. Downstream facts whose lineage transitively cites the contradicted root get flagged for re-evaluation, bounded by a hop limit. Re-evaluation is a soft signal — the flagged fact is not auto-invalidated.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [write-paths.md](./write-paths.md), [bi-temporal-validity.md](./bi-temporal-validity.md), [as-of-retrieval.md](./as-of-retrieval.md), [source-identity-and-reliability.md](./source-identity-and-reliability.md), [revision-compaction.md](./revision-compaction.md).
**Depended on by:** —

---

## Current state

`write-paths.md` (spec 4) AC-4.1 mints a REGRET on contradiction with surprise / affect thresholds. The new REGRET's initial weight is derived from `affect` only. Two real signals are not used:

- **Hold duration**: a wrong belief held for one hour vs. six months is not equally costly to the Conduit.
- **Load-bearing**: a wrong belief whose downstream conclusions cite it (directly or transitively) has cascading consequences. Citation count is a proxy for that cost.

Additionally, when a load-bearing root is contradicted, the cited downstream facts are *not flagged*. They keep ranking and feeding retrieval as if their basis were sound.

## Target

1. REGRET weight scales as a function of hold duration and citation count.
2. On supersession, enumerate downstream facts whose lineage transitively cites the superseded fact within a bounded hop limit; flag each as `needs_reeval` with the root cause recorded.
3. Re-evaluation is a soft signal. The flagged fact's `valid_from` / `valid_to` and `superseded_by` are unchanged. A detector drains the queue at low priority, surfacing each flagged fact as an ingestion candidate that the Conduit re-decides next time the topic is touched.

### Severity formula

```
hold_days       = max(0, (supersession.event_at - predecessor.created_at).days)
citation_count  = repo.count_downstream_citers(predecessor.memory_id, max_hops=REEVAL_MAX_HOPS)
severity        = ALPHA_HOLD * log1p(hold_days) + BETA_CITATIONS * log1p(citation_count)
weight          = clamp_weight(REGRET, SEVERITY_BASE + severity / SEVERITY_SCALE)
```

Defaults: `ALPHA_HOLD = 0.05`, `BETA_CITATIONS = 0.10`, `SEVERITY_BASE = 0.65`, `SEVERITY_SCALE = 1.0`, `REEVAL_MAX_HOPS = 3`. A 1-day, 0-citation regret sits at the REGRET floor (0.6); a 90-day, 30-citation regret reaches ≥ 0.95.

### Citer enumeration

A fact `C` is a *citer* of `R` iff:

- `R.memory_id ∈ C.context.cites` (explicit forward citation), OR
- `C.supersedes` chain transitively traces back through `R.memory_id`.

Both contribute to `count_downstream_citers`. Dedup by `memory_id` so a fact that is both a forward citer and a chain descendant is counted once.

### Cascade

On supersession of `R`:

```
for each citer C of R within REEVAL_MAX_HOPS hops:
    insert into memory_reeval_queue (C.memory_id, root_id=R.memory_id, hops_from_root=hops, flagged_at=now)
        on conflict (memory_id, root_id) do nothing
```

The queue is drained by a detector — `reeval_drainage` (P11 class, pattern from `detectors/README.md`) — which picks one row per tick, builds an ingestion candidate carrying `(flagged_memory, root_supersession, successor)`, and submits to the motivation backlog. On dispatch, the ingestion path may confirm (no change), supersede (standard path), or contradict (mint a fresh REGRET via spec 4, possibly cascading further). Cascade events are themselves bounded: the secondary cascade does not flag the original root again (idempotency on `(memory_id, root_id)`).

## Acceptance criteria

### Severity formula

- **AC-60.1.** REGRET minted by the spec-4 path uses `regret_weight(predecessor, supersession_event_at, repo)`. Test with `hold_days = 1, citation_count = 0` → weight at REGRET floor (0.6). Test with `hold_days = 90, citation_count = 30` → weight ≥ 0.95.
- **AC-60.2.** `severity` is bounded by `clamp_weight(REGRET, ...)`; no formula choice can exceed 1.0. Property test over random non-negative inputs.
- **AC-60.3.** Determinism: same `(predecessor, supersession_event_at, repo state)` produces the same weight on every call. Test.

### Citer enumeration

- **AC-60.4.** `count_downstream_citers(id, max_hops=3)` returns the count over `context.cites` references and supersedes-transitive descendants, deduped by `memory_id`. Fixture: A is cited (in `context.cites`) by B; B is superseded by C; C cites D and E. `count(A, max_hops=3)` returns 4 (B, C, D, E). Test.
- **AC-60.5.** Hops greater than `max_hops` are not counted. Fixture extends to F cited by E; `count(A, max_hops=2)` excludes F. Test.
- **AC-60.6.** Self-reference cycles cannot occur (supersedes is acyclic per spec 1) but `context.cites` is freeform. The walk maintains a `visited` set keyed by `memory_id` and short-circuits cycles. Test with a fixture that cites a cycle.

### Cascade and queue

- **AC-60.7.** Schema migration creates `memory_reeval_queue`: `memory_id TEXT NOT NULL`, `root_id TEXT NOT NULL`, `flagged_at TIMESTAMP NOT NULL`, `hops_from_root INTEGER NOT NULL`, `resolved_at TIMESTAMP`. Primary key `(memory_id, root_id)`. Partial index on `resolved_at IS NULL`. Test migration UP/DOWN.
- **AC-60.8.** `cascade_reeval(root_id, max_hops, repo)` writes one row per distinct `(memory_id, root_id)` pair within `max_hops`. Idempotent — re-running on the same root produces no new rows. Test.
- **AC-60.9.** A flagged memory is *not* mutated. `valid_from`, `valid_to`, `superseded_by`, `weight` are unchanged. Test asserts no mutation on the flagged row.
- **AC-60.10.** `flagged_at` is the supersession event time, not `now()` at cascade-walk time. Reproducibility for replay/audit. Test.
- **AC-60.11.** `cascade_reeval` is `O(citers × max_hops)` worst case. Benchmark with 1000 citers and depth 3 ≤ 100ms. Test.

### Drainage detector

- **AC-60.12.** `reeval_drainage` detector (P11 class, pattern from `detectors/README.md`) registers a per-tick handler that picks one unresolved queue row, constructs an ingestion candidate with payload `{flagged_memory_id, root_id, hops_from_root}`, and submits to the motivation backlog. Test the candidate construction.
- **AC-60.13.** Drainage is FIFO over `flagged_at`. Test ordering.
- **AC-60.14.** A flagged memory that is itself superseded after flagging (by an unrelated event) marks its queue row as `resolved_at = now()` with `resolution_reason = 'superseded_externally'`. The detector skips resolved rows. Test.
- **AC-60.15.** A drainage candidate dispatched and confirmed (the ingestion path concludes the flagged memory is still correct) marks the queue row resolved with `resolution_reason = 'confirmed'`. Test.
- **AC-60.16.** A drainage candidate that mints a fresh REGRET (the flagged memory was wrong) cascades again from the new supersession, bounded by `REEVAL_MAX_HOPS` from the new event — not the original. Test that secondary cascade does not re-flag the same `(memory_id, original_root_id)`.

### Compaction

- **AC-60.17.** `revision-compaction.md` (spec 53) extension: queue rows with `resolved_at` set and older than 90 days are deleted in the weekly compaction sweep. Test.

### Configuration

- **AC-60.18.** Constants overridable via config. `REEVAL_MAX_HOPS > 5` emits a warning at startup (combinatorial cost). Test the warning at 6.

## Implementation

```python
# write-paths.py — REGRET write extension

from math import log1p

ALPHA_HOLD = 0.05
BETA_CITATIONS = 0.10
SEVERITY_BASE = 0.65
SEVERITY_SCALE = 1.0
REEVAL_MAX_HOPS = 3


def regret_weight(
    predecessor: EpisodicMemory,
    supersession_event_at: datetime,
    repo: Repo,
) -> float:
    hold_days = max(0, (supersession_event_at - predecessor.created_at).days)
    citers = repo.count_downstream_citers(predecessor.memory_id, max_hops=REEVAL_MAX_HOPS)
    severity = ALPHA_HOLD * log1p(hold_days) + BETA_CITATIONS * log1p(citers)
    return clamp_weight(MemoryTier.REGRET, SEVERITY_BASE + severity / SEVERITY_SCALE)
```

```python
# reeval.py

def cascade_reeval(root_id: str, supersession_event_at: datetime, repo: Repo, max_hops: int = REEVAL_MAX_HOPS) -> int:
    visited: set[str] = {root_id}
    queue: list[tuple[str, int]] = [(root_id, 0)]
    flagged = 0
    while queue:
        node, hops = queue.pop()
        if hops >= max_hops:
            continue
        for citer in repo.find_citers(node):
            if citer.memory_id in visited:
                continue
            visited.add(citer.memory_id)
            repo.flag_reeval(
                memory_id=citer.memory_id,
                root_id=root_id,
                hops_from_root=hops + 1,
                flagged_at=supersession_event_at,
            )
            flagged += 1
            queue.append((citer.memory_id, hops + 1))
    return flagged
```

Migration:

```sql
CREATE TABLE memory_reeval_queue (
    memory_id        TEXT NOT NULL,
    root_id          TEXT NOT NULL,
    flagged_at       TIMESTAMP NOT NULL,
    hops_from_root   INTEGER NOT NULL,
    resolved_at      TIMESTAMP,
    resolution_reason TEXT,
    PRIMARY KEY (memory_id, root_id)
);
CREATE INDEX idx_reeval_unresolved ON memory_reeval_queue(flagged_at)
    WHERE resolved_at IS NULL;
```

## Open questions

- **Q60.1.** `α` and `β` are tunable. Initial values are guessed; observe the resulting REGRET weight distribution after Tranche 11 lands and recalibrate against a sample of regret events.
- **Q60.2.** The supersedes-transitive-back walk in `count_downstream_citers` is the load-bearing part — it counts descendants whose existence depended on the contradicted root. The forward `context.cites` walk catches direct citations. Both are needed; some descendants are both. Dedup by `memory_id`.
- **Q60.3.** Cascade depth = 3 default. With branching factor 4, a single root flags up to ~84 facts. Acceptable; if branching factor explodes in production, consider depth-1 only and rely on transitive flagging via secondary drainage events.
- **Q60.4.** The cascade walk — specifically `find_citers` over the supersedes-back chain — is the strongest single argument in the corpus for graph-DB extensions. A recursive CTE handles depth 3 in Postgres; deeper or denser graphs benefit from native traversal. Deferred to graph-DB integration research — see Stronghold issue #1233.
- **Q60.5.** Cascade across `valid_*` boundaries (a fact valid only in a window cites a root that was contradicted *outside* the window) is a subtle case. Current spec: still flag it; the drainage detector decides whether the contradiction is relevant. Deferred property test.
- **Q60.6.** Drainage is FIFO over `flagged_at`. Alternative: priority by hops-from-root (closer first) or by citing-fact's weight (more load-bearing first). FIFO is simplest and avoids starvation; revisit when queue depth becomes a problem.
