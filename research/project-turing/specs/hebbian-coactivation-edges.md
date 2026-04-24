# Spec 101 — Hebbian coactivation edges

*Nodes that co-activate in the same perception step accrue a small rule-origin contributor edge (weight ≤ 0.05, TTL 28 days). The self integrates progressively without explicit authoring — "neurons that fire together wire together." Decays without reinforcement.*

**Depends on:** [activation-graph.md](./activation-graph.md), [self-write-preconditions.md](./self-write-preconditions.md), [retrieval-contributor-gc.md](./retrieval-contributor-gc.md).

---

## Current state

The activation graph (spec 25) has nodes with `active_now` values propagated via contributor edges. Edges today are authored (by dreaming, detector promotions, operator writes) — there's no mechanism by which frequent co-occurrence in perception alone strengthens relatedness. OpenMemory's coactivation scoring is the reference. Without this, the graph learns only via explicit authoring, which is slower than human-like association.

## Target

Within a perception step, any pair of nodes with `active_now > θ` (default 0.3) accrues a **rule-origin, subtype=`hebbian`** contributor edge (one directional edge per ordered pair, weight ≤ 0.05, TTL 28 days). Re-coactivation resets the TTL. Per-request cap on new edges prevents runaway. Does **not** fire for retrieval-origin contributors (only stable nodes). Spec 50 GC sweeps untouched hebbian edges. Disabled at bootstrap until first retest.

## Acceptance criteria

### Detection

- **AC-101.1.** Coactivation detection runs at the end of each perception step — after all contributor propagation but before retrieval-result selection. Test ordering via a golden integration test.
- **AC-101.2.** Coactivation threshold `HEBBIAN_ACTIVATION_MIN = 0.3` on `active_now`; both endpoints must exceed it. Test at 0.29, 0.30, 0.31 boundaries.
- **AC-101.3.** Only **stable nodes** participate — nodes currently marked with `origin = "retrieval_transient"` (spec retrieval-contributor-gc.md) are excluded from both endpoints. Test with a mix.

### Edge formula

- **AC-101.4.** Edge weight formula: `w = min(HEBBIAN_MAX_WEIGHT, a_src * a_tgt * HEBBIAN_COEFFICIENT)` where `HEBBIAN_COEFFICIENT = 0.05` and `HEBBIAN_MAX_WEIGHT = 0.05`. Test with `a_src=a_tgt=1.0` produces 0.05.
- **AC-101.5.** Edges are **directional** — for a coactivated pair `(A, B)`, we write `A→B` AND `B→A` (two edges). Test both are present.
- **AC-101.6.** Edge tags: `origin = "rule"`, `subtype = "hebbian"`, `rationale = f"coactivation a={a_src:.2f},{a_tgt:.2f}"`. Test.

### TTL and reinforcement

- **AC-101.7.** TTL default `HEBBIAN_TTL_DAYS = 28`. Edges persist `expires_at = now + TTL` and are GC-swept by spec 50 after expiry. Test GC removes expired hebbian edges.
- **AC-101.8.** On re-coactivation of an existing `A→B` hebbian edge, `expires_at` is reset to `now + TTL` AND the weight is **averaged** with the new computation (not summed) to keep weights bounded. Test with two sequential coactivations at different activation levels.
- **AC-101.9.** Reinforcement never raises a hebbian edge above `HEBBIAN_MAX_WEIGHT`. Test with consistently high activations.

### Per-request cap

- **AC-101.10.** Per-perception-step cap `HEBBIAN_EDGE_CAP_PER_STEP = 10` on **new** edges (reinforcements of existing edges don't count). Beyond the cap, the top-N strongest pairs win; excess are dropped silently. Test with 15 eligible pairs.
- **AC-101.11.** Cap is enforced in conjunction with spec 38 activation cap (K≤8 contributors per target, Σ|weight|≤1.0) — if adding a hebbian edge would violate spec 38, evict the weakest existing hebbian edge on that target first; if all contributors are non-hebbian, skip the hebbian write entirely. Test both eviction paths.

### Exclusions

- **AC-101.12.** Hebbian does **not** fire when source or target is a retrieval-transient contributor (AC-101.3 enforces this at detection, AC-101.12 is the explicit negative test). Test: inject a transient retrieval node with high activation and confirm no hebbian edge is written.
- **AC-101.13.** Hebbian does not fire on self-edges (`source == target`). Test.

### Bootstrap gate

- **AC-101.14.** Disabled at bootstrap until a "first retest" signal (spec self-write-preconditions.md: `bootstrap_complete AND first_retest_passed`). Before the gate opens, detection is a no-op. Test both states.
- **AC-101.15.** Feature flag `hebbian_enabled: bool` in config (default `True` post-bootstrap) allows operator kill-switch. Test toggle.

### GC integration

- **AC-101.16.** Spec 50 GC sweep identifies hebbian edges by `origin="rule" AND subtype="hebbian"` and removes those with `expires_at < now`. Spec 50 metrics include a `turing_hebbian_edges_gc_total` counter. Test GC run removes exactly the expired subset.

### Observability

- **AC-101.17.** Prometheus gauge `turing_hebbian_edges_active{self_id}` (total count of non-expired hebbian edges). Histogram `turing_hebbian_edges_created_per_step{self_id}`. Test both.

## Implementation

```python
# activation/hebbian.py

HEBBIAN_ACTIVATION_MIN: float = 0.3
HEBBIAN_COEFFICIENT: float = 0.05
HEBBIAN_MAX_WEIGHT: float = 0.05
HEBBIAN_TTL_DAYS: int = 28
HEBBIAN_EDGE_CAP_PER_STEP: int = 10

def apply_hebbian(
    repo, self_id: str, active_nodes: list[ActiveNode], *, now: datetime,
) -> int:
    if not _bootstrap_and_retest_ok(repo, self_id):
        return 0
    stable = [n for n in active_nodes
              if n.active_now >= HEBBIAN_ACTIVATION_MIN
              and n.origin != "retrieval_transient"]
    pairs = [
        (a, b, a.active_now * b.active_now * HEBBIAN_COEFFICIENT)
        for a in stable for b in stable if a.id != b.id
    ]
    pairs.sort(key=lambda p: -p[2])
    existing_reinforced = 0
    new_written = 0
    for src, tgt, w in pairs:
        w = min(w, HEBBIAN_MAX_WEIGHT)
        existing = repo.find_hebbian_edge(self_id, src.id, tgt.id)
        if existing is not None:
            repo.reinforce_hebbian(existing, weight=(existing.weight + w)/2,
                                   expires_at=now + timedelta(days=HEBBIAN_TTL_DAYS))
            existing_reinforced += 1
        elif new_written < HEBBIAN_EDGE_CAP_PER_STEP:
            if _respects_spec38_cap(repo, tgt.id, w):
                repo.insert_hebbian(self_id, src.id, tgt.id, weight=w,
                                    expires_at=now + timedelta(days=HEBBIAN_TTL_DAYS))
                new_written += 1
    return new_written
```

## Open questions

- **Q101.1.** Averaging on reinforcement is conservative; could instead use exponential moving average with α=0.3. Deferred to tuning once we observe hebbian-edge distributions.
- **Q101.2.** 28-day TTL may be too long for memories that coactivate once and never again; a shorter initial TTL that extends on reinforcement could be more adaptive. Consider a two-phase TTL (7d on first creation, 28d on first reinforcement).
- **Q101.3.** Hebbian edges at weight 0.05 are low but can accumulate to ~0.4 in aggregate if many coactivate a single target. Spec 38's Σ|weight|≤1.0 cap saves us — worth verifying in load tests.
- **Q101.4.** Should retrieval-transient nodes ever seed hebbian edges if they're re-retrieved consistently? Currently no. An alternative is to promote persistent transient nodes to stable and then let hebbian fire. Deferred.
