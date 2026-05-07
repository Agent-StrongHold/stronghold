# Spec 25 — Activation graph

*Nodes don't compute their own activation. Other nodes, memories, and events contribute to them through explicit edges. The self authors the ontology.*

**Depends on:** [self-schema.md](./self-schema.md), [personality.md](./personality.md), [self-nodes.md](./self-nodes.md).
**Depended on by:** [self-surface.md](./self-surface.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- Memory retrieval uses a single similarity × weight score (spec 16). There is no structural notion of "this memory is evidence *of* facet X" or "this passion reinforces hobby Y."
- Personality facets hold a score; passions/preferences hold a strength; hobbies/interests hold no weight. None of them have a notion of "how activated am I on this right now" that combines self-authored structure with retrieval signal.

## Target

Every self-model node has an `active_now(node_id, context)` computed value in `[0.0, 1.0]` (normalized) derived from incoming contributor edges. Edges are either durable (`origin ∈ {self, rule}`) or ephemeral (`origin = retrieval`, TTL-bounded). The self owns the graph — edges are created by the self via `write_contributor(...)` during reflection, by rules at bootstrap/install time, or by retrieval at request time.

## Acceptance criteria

### Contributor rows

- **AC-25.1.** An `ActivationContributor` row is `(target_node_id, target_kind, source_id, source_kind, weight, origin, rationale, expires_at?)`. Schema constraints from spec 22 (AC-22.19–22.21) apply. Test.
- **AC-25.2.** `origin = self` rows have no `expires_at` and persist until explicitly retracted. `origin = rule` rows have no `expires_at` and persist until the rule is unloaded. `origin = retrieval` rows have `expires_at = now() + RETRIEVAL_TTL` (default 5 minutes). Test each.
- **AC-25.3.** `source_kind` ∈ `NodeKind` ∪ `{"memory", "rule", "retrieval"}`. Test for each value.
- **AC-25.4.** `weight ∈ [-1.0, 1.0]`. Negative weights are inhibitory — they subtract from target activation. Test with a target fed a +0.5 and a -0.3 contributor asserts the sum is +0.2 before normalization.
- **AC-25.5.** A contributor where `target == source` raises (no self-loops). Test.

### Activation computation

- **AC-25.6.** `active_now(node_id, context)` fetches all non-expired contributors for `node_id`, computes each contributor's `weight × source_state(source_id, source_kind, context)`, sums, then normalizes with a bounded activation function:

  ```
  raw   = Σ weight × source_state
  active_now = clamp(sigmoid(raw / SCALE), 0.0, 1.0)
  ```

  where `SCALE = 2.0` seeds the steepness and is tunable. Test against fixed inputs.

- **AC-25.7.** `source_state(source_id, source_kind, context)` resolves the source's current state into `[0.0, 1.0]`:
  - `source_kind == personality_facet`: `(score - 1.0) / 4.0` (remap 1..5 to 0..1).
  - `source_kind == passion` or `preference`: `strength`.
  - `source_kind == hobby` or `interest`: `1.0 if last_engaged/noticed within HOBBY_RECENCY_DAYS else recency_decay`.
  - `source_kind == mood`: a dimension chosen by the contributor's `rationale` parsing (default: valence mapped to `[0,1]`).
  - `source_kind == memory`: `clamp(memory.weight, 0.0, 1.0)`.
  - `source_kind == rule`: `1.0` (rules are always "on" at full strength; the edge's own `weight` scales them).
  - `source_kind == retrieval`: `similarity_score` from the retrieval query that created the edge.

  Each sub-rule has a unit test.

- **AC-25.8.** `active_now` is deterministic given the same `(node_id, context, clock)`. Two calls back-to-back return identical values. Test.
- **AC-25.9.** `active_now` is a read-only computation — no persistence writes. Test.
- **AC-25.10.** Cache: `active_now` results are cached per `(node_id, context_hash)` for `ACTIVATION_CACHE_TTL` (default 30 seconds). Cache is invalidated when any contributor targeting that node is written or expires. Test asserts cache hit on repeated call and cache miss after a relevant contributor write.

### Retrieval contributor lifecycle

- **AC-25.11.** At request-time, the self (or the Conduit pipeline on its behalf) runs a semantic retrieval over memory + durable self-nodes and materializes the top-K matches as `origin = retrieval` contributors with `weight = similarity_score × RETRIEVAL_WEIGHT_COEFFICIENT` and `expires_at = now() + RETRIEVAL_TTL`. `K` defaults to 8. Test.
- **AC-25.12.** After `RETRIEVAL_TTL`, expired retrieval contributors are garbage-collected on the next read touching that target OR every `RETRIEVAL_GC_INTERVAL` ticks, whichever comes first. Test asserts expired rows are not returned by `active_now` even if not yet GC'd.
- **AC-25.13.** A retrieval contributor is never written with `origin = self` or `origin = rule`. Test that `write_contributor(...)` with `origin = retrieval` raises — only the retrieval pipeline can mint retrieval edges.

### Conflict resolution

- **AC-25.14.** Two contributors from different sources cannot directly conflict (they sum). Test.
- **AC-25.15.** When the self wants to override a rule-origin contributor it disagrees with, it writes a **competing self-origin contributor** with opposite sign and declares the rule's edge retracted-by-self (a new column on the contributor: `retracted_by: node_id | None`; when set, the edge is excluded from `active_now`). A self cannot retract its own past contributors — it must write a new one to counteract. Test.
- **AC-25.16.** Primacy across multiple self-authored contributors: when two self contributors target the same node with opposite signs, the one with the larger absolute weight wins that round of sum. This is the same mechanism used by passion primacy (spec 24 AC-24.6). Test.

### Write path

- **AC-25.17.** `write_contributor(target, source, weight, rationale, origin=SELF)` is a tool exposed to the self. It validates constraints (no self-loops, `source_kind` valid, weight in range), inserts the row, and invalidates the target's cache. Test.
- **AC-25.18.** Rules are loaded at deployment time from `research/project-turing/config/activation_rules.yaml`. Format: `target_kind`, `source_pattern`, `weight`, `rationale`. Rule rows are materialized at load. Unloading a rule removes its contributor rows. Test against a fake rules file.
- **AC-25.19.** Every `write_contributor` also creates an OBSERVATION-tier memory with `content = f"[contributor] {source_id} → {target_node_id} weight={weight}: {rationale}"`. Provides an audit trail for the self's ontology decisions. Test.

### Edge cases

- **AC-25.20.** A target with zero durable contributors returns `active_now = 0.5` (neutral baseline, the sigmoid of 0). Documented as a semantic choice: an un-evidenced node is not "off," it's "indeterminate." Test.
- **AC-25.21.** A target with only inhibitory contributors returns `active_now < 0.5`. A target with only excitatory contributors returns `active_now > 0.5`. Property test over random contributor sets.
- **AC-25.22.** A target whose contributors sum to > +10.0 (dominant) still saturates at `active_now → 1.0` via sigmoid; it cannot exceed 1.0. Property test.
- **AC-25.23.** A contributor whose source was hard-deleted (operator action) is detected at read time and treated as weight-0 for this compute, with a warning logged. Row stays in place for forensics. Test.
- **AC-25.24.** A rule pattern that matches no live nodes at load time logs a warning but does not fail the load. Test.

## Implementation

### 25.1 Source state resolution

```python
def source_state(
    repo: SelfRepo,
    source_id: str,
    source_kind: str,
    context: ActivationContext,
) -> float:
    if source_kind == "personality_facet":
        facet = repo.get_facet(source_id)
        return max(0.0, min(1.0, (facet.score - 1.0) / 4.0))
    if source_kind == "passion":
        p = repo.get_passion(source_id)
        return p.strength
    if source_kind == "preference":
        p = repo.get_preference(source_id)
        return p.strength
    if source_kind == "hobby":
        h = repo.get_hobby(source_id)
        return _recency_state(h.last_engaged_at, context.now, HOBBY_RECENCY_DAYS)
    if source_kind == "interest":
        i = repo.get_interest(source_id)
        return _recency_state(i.last_noticed_at, context.now, INTEREST_RECENCY_DAYS)
    if source_kind == "mood":
        m = repo.get_mood(context.self_id)
        return (m.valence + 1.0) / 2.0
    if source_kind == "memory":
        mem = repo.get_memory(source_id)
        return max(0.0, min(1.0, mem.weight))
    if source_kind == "rule":
        return 1.0
    if source_kind == "retrieval":
        return context.retrieval_similarity.get(source_id, 0.0)
    raise ValueError(f"unknown source_kind: {source_kind}")
```

### 25.2 Activation formula

```python
import math

SCALE: float = 2.0

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def active_now(
    repo: SelfRepo,
    node_id: str,
    context: ActivationContext,
) -> float:
    cached = _cache_get(node_id, context.hash)
    if cached is not None:
        return cached

    contribs = repo.active_contributors_for(node_id, at=context.now)
    raw = 0.0
    for c in contribs:
        if c.retracted_by is not None:
            continue
        s = source_state(repo, c.source_id, c.source_kind, context)
        raw += c.weight * s

    value = max(0.0, min(1.0, _sigmoid(raw / SCALE)))
    _cache_put(node_id, context.hash, value, ttl=ACTIVATION_CACHE_TTL)
    return value
```

### 25.3 Recency helper

```python
def _recency_state(last: datetime | None, now: datetime, window_days: float) -> float:
    if last is None:
        return 0.0
    days = (now - last).total_seconds() / 86400.0
    if days <= 0:
        return 1.0
    if days >= window_days:
        return 0.0
    return 1.0 - (days / window_days)
```

### 25.4 Constants

```python
RETRIEVAL_TTL:                  timedelta = timedelta(minutes=5)
RETRIEVAL_WEIGHT_COEFFICIENT:   float = 0.4   # top-sim becomes a +0.4 edge
RETRIEVAL_GC_INTERVAL_TICKS:    int = 1000    # reactor ticks
ACTIVATION_CACHE_TTL:           timedelta = timedelta(seconds=30)
HOBBY_RECENCY_DAYS:             float = 14.0
INTEREST_RECENCY_DAYS:          float = 30.0
```

## Open questions

- **Q25.1.** `SCALE = 2.0` in the sigmoid. With SCALE=1, a raw sum of 2 produces active=0.88; with SCALE=2, the same raw sum produces active=0.73. Softer seed reduces feedback loops where one strongly-activated node dominates many others. Tunable.
- **Q25.2.** `RETRIEVAL_WEIGHT_COEFFICIENT = 0.4` bounds retrieval contributions below self-authored edges (which can be ±1.0). Keeps durable authored structure dominant over transient retrieval signal. Tunable but deliberate.
- **Q25.3.** `active_now = 0.5` for zero-contributor nodes is semantically "indeterminate." An alternative is 0.0 ("unevidenced = off"). The 0.5 choice makes un-wired nodes neutral in the prompt surface rather than pulling scores down.
- **Q25.4.** Retracted-by-self contributors remain as rows with a `retracted_by` field. This means the graph accumulates rows over time. A scheduled `compact_retractions` job could physically remove retracted rows whose retractor is itself still live. Deferred.
- **Q25.5.** Rule-origin contributors always resolve to `source_state = 1.0`. An alternative is to let rules declare a weighting function over the request context (e.g., "this rule fires at strength 0.3 when the request is a voice call, else 1.0"). Deferred as rule-authoring complexity.
- **Q25.6.** Cross-node cycles. The graph permits A → B and B → A (reciprocal contributors per spec 24 AC-24.18). `active_now` computation is one-shot (not iterative fixed-point), so a cycle is just a mutual contribution at a single evaluation step. No divergence risk. But a chain A → B → C → A, all at weight 1.0, would let the self's activation propagate around. Documented as intended behavior; a detector could flag suspicious cycle density for review.
