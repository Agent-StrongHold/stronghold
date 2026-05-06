# Spec 58 — As-of retrieval (time-travel queries)

*A retrieval mode that returns the memories the Conduit would have surfaced at a past time `t`. Built on bi-temporal validity (spec 57); orthogonal to the supersedes lineage walk in `retrieval.md`.*

**Depends on:** [bi-temporal-validity.md](./bi-temporal-validity.md), [retrieval.md](./retrieval.md), [semantic-retrieval.md](./semantic-retrieval.md), [persistence.md](./persistence.md).
**Depended on by:** [regret-severity-and-load-bearing.md](./regret-severity-and-load-bearing.md) (severity needs to know what would have been surfaced when the wrong belief was held), [journal.md](./journal.md) (multi-resolution narrative reconstruction).

---

## Current state

`retrieval.md` (spec 6) and `semantic-retrieval.md` (spec 16) operate on *now*. They walk the supersedes chain to surface the latest live form of a memory and skip dangling/superseded predecessors. There is no way to ask "what would I have answered at time `t`?"

`forensic-tagging.md` (spec 39) provides the audit thread to recover *what was written* by a request, but not *what would have been retrieved* by a hypothetical request at a past time.

This gap matters for three downstream needs: severity-of-regret calculation (how long did the Conduit hold the wrong belief, and what would it have answered with?), journal reconstruction ("what did I think a month ago about X?"), and audit (operator wants to replay a past request through past beliefs).

## Target

A retrieval mode `as_of(t)` that surfaces the set of memories the Conduit *would have* surfaced at `t`. Visibility predicate — a memory is visible iff *all* hold:

- `created_at <= t` — the Conduit had recorded the memory by `t`.
- `valid_from IS NULL OR valid_from <= t` — the fact had begun in the world by `t`.
- `valid_to IS NULL OR valid_to > t` — the fact had not yet ended in the world at `t`.
- The memory was not yet superseded at `t`. Equivalent to: the first successor in the chain whose `created_at <= t` does not exist.
- Soft-deleted only if `deleted_at` is set and `deleted_at <= t`.

*Out of scope*: "historical-knowledge queries" — e.g., "what does the Conduit, asked today, know about a state of the world at time `s`?" — are a different beast (project-historical reconstruction). They require walking forward in `valid_from`/`valid_to` rather than freezing the visibility window. A separate spec, if and when needed.

## Acceptance criteria

- **AC-58.1.** `repo.as_of(t).get(memory_id)` returns the memory iff visible per the predicate above; raises `KeyError` otherwise. Test with a fact created at `t1`: `as_of(t0 < t1)` raises; `as_of(t1)` returns. Test with a successor at `t2 > t1`: `as_of(t1+ε)` returns the predecessor; `as_of(t2+ε)` returns the successor.
- **AC-58.2.** `repo.as_of(t).search(query, k=...)` runs the same hybrid pipeline as `now()` retrieval (spec 16) with the visibility predicate substituted for the live-only predicate. Test with a semantic query that matches a fact only inside its validity window.
- **AC-58.3.** A fact with `valid_from = None`, `valid_to = None` is visible for any `t >= created_at`. Test.
- **AC-58.4.** A fact with explicit `valid_from` and `valid_to` is visible at `t` iff `t >= created_at AND valid_from <= t < valid_to`. Test all three boundary conditions.
- **AC-58.5.** Lineage walk: a chain `A -> B -> C` (B supersedes A, C supersedes B) with `created_at` `t_a < t_b < t_c`. `as_of(t_a)` returns A. `as_of((t_a + t_b) / 2)` returns A. `as_of(t_b)` returns B. `as_of((t_b + t_c) / 2)` returns B. `as_of(t_c)` returns C. Test the full table.
- **AC-58.6.** Soft-delete handling: a memory deleted at `t_d` is visible for `t < t_d` and invisible for `t >= t_d`. Test. (Soft-delete schema extension is a sibling spec; this AC documents the contract.)
- **AC-58.7.** Performance: `as_of(t)` adds at most `O(log n)` overhead vs. now-retrieval through the composite index `(valid_from, valid_to)` from spec 57 plus a `created_at` index. Benchmark: 10k-row fixture, p95 latency overhead ≤ 10ms. Test.
- **AC-58.8.** CLI: `stronghold inspect retrieval --as-of <iso8601> --query <q>` returns the as-of result set with a header line stating `t` and the count of facts the predicate excluded vs. now-retrieval. Test the CLI parses ISO 8601 and rejects invalid timestamps.
- **AC-58.9.** `as_of(t)` is read-only — calling it on a `RepoWriter` does not allow mutation. Test by attempting a write through the as-of view; it raises.
- **AC-58.10.** Property test: for any fact `m` and any `t1 <= t2`, if `m` is visible at both, then `m` is visible at every `t ∈ [t1, t2]` (visibility is interval-monotonic per fact).

## Implementation

```python
# repo.py — as-of view

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AsOfRepo:
    inner: Repo
    t: datetime

    def get(self, memory_id: str) -> EpisodicMemory:
        m = self.inner.get(memory_id)
        if not _visible_at(m, self.t, self.inner):
            raise KeyError(memory_id)
        return m

    def search(self, query: str, k: int = 8) -> list[EpisodicMemory]:
        candidates = self.inner.search_unfiltered(query, k=k * 4)
        return [m for m in candidates if _visible_at(m, self.t, self.inner)][:k]


def _visible_at(m: EpisodicMemory, t: datetime, repo: Repo) -> bool:
    if m.created_at > t:
        return False
    if m.valid_from is not None and m.valid_from > t:
        return False
    if m.valid_to is not None and m.valid_to <= t:
        return False
    if m.deleted_at is not None and m.deleted_at <= t:
        return False
    if m.superseded_by is not None:
        successor = repo.get(m.superseded_by)
        if successor.created_at <= t:
            return False
    return True
```

Over-fetch by `4x` in `search` to absorb predicate filtering at retrieval time. The `now()` retrieval can stay unchanged; both paths share `search_unfiltered`.

## Open questions

- **Q58.1.** Embeddings are computed at write-time and reflect understanding-at-write, not understanding-at-`t`. Semantic search at `as_of(t)` uses today's embeddings against a `t`-filtered candidate set. This is acceptable lossiness — the alternative (embedding rewrites at every supersession) is prohibitive. Documented; revisit if a property test reveals retrieval drift > 5% across long time windows.
- **Q58.2.** Soft-delete needs a `deleted_at` column. The current schema (spec 1) uses `deleted: bool`. Migration to `deleted_at: datetime | None` with backfill `deleted_at = created_at` for currently-deleted rows is a sibling spec to land before this one; flagged for the reviewer.
- **Q58.3.** Bulk historical reconstruction (e.g., journal's "week resolution") asks `as_of(t)` repeatedly across a window. A batched API `repo.as_of_bulk(timestamps, query)` could share candidate fetches; defer until journal performance demands it.
- **Q58.4.** Lineage walks at depth ("show me the chain that led from this fact to its eventual REGRET, with each step's as-of view") would benefit from native graph traversal. Deferred to graph-DB integration research — see Stronghold issue #1233.
- **Q58.5.** Concurrent supersession during an `as_of` query (fact superseded between candidate fetch and predicate check) is harmless — the snapshot is whatever the read transaction sees. Document; no extra locking needed.
