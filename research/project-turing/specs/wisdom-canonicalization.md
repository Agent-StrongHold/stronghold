# Spec 97 — WISDOM canonicalization

*Before minting a new WISDOM during dreaming, embed-compare against existing WISDOMs; if a near-duplicate exists, reinforce it with a small contributor edge instead of creating a parallel belief.*

**Depends on:** [wisdom-write-path.md](./wisdom-write-path.md), [dreaming.md](./dreaming.md), [semantic-retrieval.md](./semantic-retrieval.md), [activation-graph.md](./activation-graph.md), [near-duplicate-review.md](./near-duplicate-review.md).

---

## Current state

Dreaming's WISDOM-candidacy phase (spec 12) promotes stabilized LESSONs to WISDOM when they survive the identity-anchor threshold (weight floor 0.9). Nothing prevents the self from minting semantically-identical WISDOMs — "honesty matters more than comfort" and "truth beats ease" can both survive and both anchor, splintering the identity surface. ACE-style skillbook embedding dedup (the reference) solved this for skills but hasn't been ported to WISDOM.

## Target

During WISDOM candidacy, embed the candidate and cosine-compare against all existing un-retired WISDOMs. If any match has cosine ≥ 0.9, **don't mint** — instead, author a reinforcing contributor edge (origin=`dream`, default weight 0.03) from the candidate's lineage into the matched WISDOM. Below threshold, proceed to the normal write path (spec 5). Dedup is WISDOM-only — LESSONs can still proliferate versions. A candidate-table metadata row records the dedup decision for operator review.

## Acceptance criteria

### Threshold & scope

- **AC-97.1.** Dedup threshold `WISDOM_DEDUP_COSINE = 0.9`, tunable via config. Test that 0.89 mints new, 0.91 dedups.
- **AC-97.2.** Dedup compares against **WISDOMs only**, not LESSONs or any other tier. Test that a candidate matching a high-cosine LESSON still mints as WISDOM.
- **AC-97.3.** Retired/superseded WISDOMs (spec on WISDOM retirement, if present; otherwise `status != "active"`) are excluded from comparison. Test.

### Dedup action

- **AC-97.4.** On dedup hit, author a contributor edge into the matched WISDOM:
  - `origin = "dream"`
  - `weight = WISDOM_DEDUP_CONTRIBUTOR_WEIGHT` (default 0.03)
  - `rationale = f"dream dedup: candidate {candidate_id} matched at cosine={sim:.3f}"`
  Test edge is created with correct fields.
- **AC-97.5.** Dedup weight must be **≤ activation cap** (spec 38 K≤8 per target, Σ|weight|≤1.0). If adding it would exceed Σ|weight|, the edge is still added at reduced weight to fit the cap; if the cap is already saturated at 8 edges, the lowest-weight dream edge is evicted first. Test both cap conditions.
- **AC-97.6.** The dedup's match diff (candidate content vs matched WISDOM content, cosine, chosen action) is logged as an OBSERVATION with source `I_DID`, content summary ≤ 240 chars, for operator review. Test.

### Multiple matches

- **AC-97.7.** If multiple existing WISDOMs exceed threshold, pick the one with **highest contributor weight sum** (most canonical). Tie-break on `minted_at` (older wins). Test with constructed multi-match scenario.
- **AC-97.8.** Only the winner receives the reinforcing edge — losers are ignored for this candidacy. Test that exactly one edge is written.

### Normal path preservation

- **AC-97.9.** Below-threshold candidates proceed to the normal WISDOM write path (spec 5) unchanged — lineage preserved, I_DID provenance preserved, identity-anchor floor 0.9 preserved. Test by injecting a candidate with max cosine 0.5.
- **AC-97.10.** WISDOM invariants (lineage chain, I_DID source, weight ≥ 0.9) are preserved on the dedup path too — the matched WISDOM keeps its invariants; only its contributor edges grow. Test.

### Configurability

- **AC-97.11.** Dedup can be disabled per-session via config flag `wisdom_dedup_enabled: false`. When disabled, all candidates mint normally. Test toggle behavior.
- **AC-97.12.** Threshold and contributor weight are config-overridable at dream-run invocation time (not compile-time). Test override via dream-run CLI flag.

### Candidate table metadata

- **AC-97.13.** The wisdom-candidate table gains columns `dedup_matched_wisdom_id TEXT NULL`, `dedup_cosine REAL NULL`, `dedup_action TEXT NULL` (values: `"minted"`, `"deduped"`, `"disabled"`). Populated for every candidacy. Test each action code appears.
- **AC-97.14.** A schema migration adds these columns with NULL defaults; existing rows remain valid. Test migration.

### Observability

- **AC-97.15.** Prometheus counters `turing_wisdom_candidates_deduped_total{self_id}` and `turing_wisdom_candidates_minted_total{self_id}`. Test.

## Implementation

```python
# dreaming/wisdom_candidacy.py

WISDOM_DEDUP_COSINE: float = 0.9
WISDOM_DEDUP_CONTRIBUTOR_WEIGHT: float = 0.03

def attempt_wisdom_promotion(
    repo, self_id: str, candidate: WisdomCandidate, *, config: DreamConfig,
) -> WisdomOutcome:
    if not config.wisdom_dedup_enabled:
        return _mint(repo, self_id, candidate, dedup_action="disabled")

    cand_emb = embed(candidate.content)
    existing = repo.list_active_wisdoms(self_id)
    matches = [
        (w, cosine(cand_emb, w.embedding))
        for w in existing
    ]
    over_threshold = [m for m in matches if m[1] >= WISDOM_DEDUP_COSINE]

    if not over_threshold:
        return _mint(repo, self_id, candidate, dedup_action="minted")

    winner = max(
        over_threshold,
        key=lambda m: (_contributor_weight_sum(repo, m[0].id), -m[0].minted_at.timestamp()),
    )[0]
    _add_dedup_edge(repo, winner.id, candidate, weight=WISDOM_DEDUP_CONTRIBUTOR_WEIGHT)
    _log_dedup_observation(repo, self_id, candidate, winner, cosine=over_threshold[0][1])
    repo.record_candidacy(candidate.id, dedup_matched=winner.id, action="deduped")
    return WisdomOutcome(deduped_into=winner.id)
```

## Open questions

- **Q97.1.** Cosine 0.9 is aggressive for short WISDOM content; could be tuned down to 0.85 once we have corpus data. Deferred to first-pass review.
- **Q97.2.** Should a dedup contributor ever "graduate" to a stronger edge on repeat hits (Hebbian-style, spec 101)? Currently no — dedup always writes 0.03. Worth considering.
- **Q97.3.** Contributor eviction at cap saturation prefers evicting oldest dream-origin edges — should operator-origin edges be evict-immune? Probably; note for activation-graph hardening.
- **Q97.4.** Multiple WISDOMs above threshold could signal genuine distinct-but-related beliefs; our tie-break collapses them. Consider a `near_duplicate_review` queue entry (spec dep) for operator adjudication when ≥ 3 matches. Deferred.
