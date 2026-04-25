# Spec 108 — Inter-tier resonance promotion

*When a non-durable memory repeatedly co-activates with a WISDOM memory over a rolling window, its promotion threshold lowers. Wisdom pulls related observations into stronger tiers — but origin-episode dampening prevents a single wisdom's echo chamber from manufacturing its own supporting evidence.*

**Depends on:** [write-paths.md](./write-paths.md), [wisdom-write-path.md](./wisdom-write-path.md), [activation-graph.md](./activation-graph.md), [retrieval.md](./retrieval.md), [durability-invariants.md](./durability-invariants.md).

---

## Current state

Promotion from OBSERVATION → HYPOTHESIS → OPINION → LESSON happens on reinforcement count and surprise_delta (spec write-paths). WISDOM is the durable top tier. Nothing today connects WISDOM activation back down the tier hierarchy: a WISDOM's retrieval does not make its neighbors easier to promote. Coactivation data exists in the activation graph (spec 62) but is only used for biasing specialist selection, not memory promotion.

## Target

A resonance mechanism: when a non-durable memory co-activates with any WISDOM memory inside a perception step repeatedly over a 14-day rolling window, the non-durable memory's promotion threshold is reduced. The reduction is capped (floor at 50% of base) and dampened when the coactivating WISDOMs all share an `origin_episode_id` — a single formative event should not conjure its own mountain of corroborating HYPOTHESES.

## Acceptance criteria

### Coactivation counting

- **AC-108.1.** Each perception step, if two memories both have `active_now > θ` (θ = 0.3, configurable via `TURING_RESONANCE_THETA`), and exactly one of them is WISDOM, append a coactivation row `(wisdom_id, other_id, step_id, occurred_at)`. Test with θ=0.3 crafted.
- **AC-108.2.** The resonance window is 14 days rolling (configurable via `TURING_RESONANCE_WINDOW_DAYS`). Older rows are pruned by a detector at P60. Test pruning.
- **AC-108.3.** Only WISDOM → non-durable resonance is counted. LESSON or AFFIRMATION on the non-durable side is skipped (LESSON → non-durable is out of scope). Test a coactivation of LESSON with OBSERVATION does not create a resonance row.

### Threshold lowering

- **AC-108.4.** For a non-durable memory `m`, `coactivation_hits(m)` = count of distinct `wisdom_id`s in the window that co-activated with `m`, each weighted by `1 / distinct_origin_episodes(wisdom_id)` when those wisdoms share an `origin_episode_id`. Test dampening: 5 WISDOMs all from the same episode count as 1, not 5.
- **AC-108.5.** `effective_threshold(m) = base_threshold(m.tier) × max(0.5, 1 − 0.1 × coactivation_hits(m))`. Test boundary: 5 hits → 0.5× base; 10 hits → still 0.5× base (floor).
- **AC-108.6.** Promotion still requires `surprise_delta > 0` (existing invariant). A memory with zero surprise never promotes regardless of resonance. Test.

### Invariant preservation

- **AC-108.7.** Resonance never bypasses durability invariants (spec 3). A REGRET does not become promotable to a lower tier; a WISDOM cannot be demoted. Test a REGRET with many resonant WISDOM coactivations does not change tier.
- **AC-108.8.** Resonance does not affect weight or weight_floor — only the promotion threshold. Test weights remain unchanged after 10 resonance hits.
- **AC-108.9.** When a non-durable memory promotes via a resonance-lowered threshold, the promotion event is recorded as an OBSERVATION: `"memory X promoted via resonance with Y, Z, ..."` including the triggering WISDOM ids. Test the OBSERVATION is minted atomically with the promotion.

### Observability

- **AC-108.10.** Prometheus counter `turing_resonance_promotions_total{self_id, target_tier}`. Test.
- **AC-108.11.** Prometheus gauge `turing_resonance_coactivations_window{self_id}` (active rows in window). Test.
- **AC-108.12.** `stronghold self digest` surfaces the top 5 WISDOMs by resonance-count-in-window. Test.

### Storage

- **AC-108.13.** New table `resonance_coactivations (id, self_id, wisdom_id, other_id, step_id, occurred_at)` with unique index on `(wisdom_id, other_id, step_id)`. Test migration is idempotent.
- **AC-108.14.** Pruning detector (P60, daily) deletes rows older than the resonance window. Test.

### Edge cases

- **AC-108.15.** A WISDOM with no `origin_episode_id` (grandfathered) is treated as its own distinct episode. Test a legacy WISDOM still contributes one resonance hit.
- **AC-108.16.** If a WISDOM is soft-archived (`archived_at IS NOT NULL`), it stops producing new resonance rows immediately and existing rows in the window decay naturally (not retroactively removed). Test.
- **AC-108.17.** Coactivation-row write is idempotent per `(wisdom_id, other_id, step_id)` triple. Retries never inflate hits. Test.
- **AC-108.18.** If `active_now` is unavailable for a step (activation-graph miss), no coactivation rows for that step are written. Test graceful skip.

## Implementation

```python
# memory/resonance.py

RESONANCE_THETA: float = 0.3
RESONANCE_WINDOW: timedelta = timedelta(days=14)
THRESHOLD_FLOOR: float = 0.5
HIT_WEIGHT: float = 0.1


def record_step_coactivations(repo, self_id: str, activations: dict[str, float], step_id: str, now: datetime) -> None:
    hot = [mid for mid, a in activations.items() if a > RESONANCE_THETA]
    tiers = repo.tiers_for(hot)
    for wid in (m for m in hot if tiers[m] == "wisdom"):
        for oid in (m for m in hot if tiers[m] not in DURABLE_TIERS and m != wid):
            repo.upsert_resonance_row(self_id, wid, oid, step_id, now)


def effective_threshold(repo, self_id: str, memory_id: str, now: datetime) -> float:
    base = BASE_THRESHOLDS[repo.tier_of(memory_id)]
    rows = repo.resonance_rows_in_window(self_id, memory_id, since=now - RESONANCE_WINDOW)
    wisdom_ids = {r.wisdom_id for r in rows}
    episodes = repo.origin_episodes_for(wisdom_ids)
    episode_counts: dict[str, int] = {}
    for wid in wisdom_ids:
        ep = episodes.get(wid) or wid  # missing origin → treat as own episode
        episode_counts[ep] = episode_counts.get(ep, 0) + 1
    hits = sum(1.0 / c for c in episode_counts.values())
    return base * max(THRESHOLD_FLOOR, 1.0 - HIT_WEIGHT * hits)
```

## Open questions

- **Q108.1.** `HIT_WEIGHT = 0.1` and floor 0.5 give a fairly gentle curve. A self accumulating many resonances against many distinct WISDOM-episodes can halve its promotion threshold. That seems right, but we need traffic data.
- **Q108.2.** We explicitly scope this to WISDOM → non-durable. LESSON → non-durable resonance is a plausible extension but risks runaway promotion chains. Deferred pending telemetry on this narrower version.
- **Q108.3.** The origin-episode dampener assumes WISDOM write paths populate `origin_episode_id` reliably. If that field is sparse at first, effective dampening is weak. Add a migration pass before enabling.
- **Q108.4.** Should a demoted or retracted WISDOM retroactively void its resonance contributions? Today we leave them in the window and let them decay naturally — cheaper, and the retraction's OBSERVATION already tells the story.
