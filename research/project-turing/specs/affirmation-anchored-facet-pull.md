# Spec 106 — AFFIRMATION-anchored facet pull

*When dreaming identifies an AFFIRMATION stable across ≥4 sessions (committed and not superseded), ask which facet would naturally underwrite the commitment and author a small reinforcing contributor from that AFFIRMATION toward the facet. Symmetrically, contradicting AFFIRMATIONs author opposing contributors so the self stays honest.*

**Depends on:** [dreaming.md](./dreaming.md), [write-paths.md](./write-paths.md), [activation-graph.md](./activation-graph.md), [facet-drift-budget.md](./facet-drift-budget.md), [dream-phase-facet-attribution.md](./dream-phase-facet-attribution.md).

---

## Current state

AFFIRMATIONs are durable `I_DID` commitments the self makes about what it stands for. Today, an AFFIRMATION influences routing bias and retrieval but does nothing to personality. That asymmetry means the self can repeatedly affirm a stance ("I prioritize clarity over speed") while its Conscientiousness / Honesty-Humility facet scores drift in directions that contradict the stance. Spec 104's dream-phase facet attribution is retrospective — it pulls facets from what just happened. Nothing pulls facets prospectively, from what the self has committed to being.

## Target

A dream-phase pass that walks stable AFFIRMATIONs (present across ≥ N dream sessions without supersession) and, via a reflector, authors a small reinforcing contributor from the AFFIRMATION toward the facet that would naturally underwrite it. Contradicting AFFIRMATIONs (opposing stances on the same topic) author opposing contributors — ensuring the self doesn't drift into trait configurations that contradict its commitments. Weights are strictly smaller than spec 104's attribution (this is prospective, not witnessed) and subject to the same facet-drift budget.

## Acceptance criteria

### Stability gate

- **AC-106.1.** An AFFIRMATION qualifies as "stable" when it has been present — neither soft-deleted nor superseded — for `AFFIRM_PULL_STABILITY_MIN_SESSIONS = 4` consecutive dream sessions. Test the counting logic, including dream-session-skip handling (a skipped session does not reset the count but does not increment it).
- **AC-106.2.** Supersession is determined by the `superseded_by` metadata field on the AFFIRMATION record; a non-null value disqualifies the ancestor. Test the check.
- **AC-106.3.** Phase disabled when `smoke_mode = True`. Test the disable.

### Facet selection via reflector

- **AC-106.4.** For each stable AFFIRMATION, invoke a reflector LLM via spec 19 `complete()` with the prompt: *"Which single HEXACO-24 facet most naturally underwrites this commitment, and in which direction (up/down)?"*. Output is a JSON object `{"facet": <one of 24>, "direction": "up"|"down"}`; malformed output is treated as no-attribution. Test malformed handling.
- **AC-106.5.** The reflector has a short timeout (`AFFIRM_PULL_REFLECTOR_TIMEOUT_SEC = 10`). On timeout, skip this AFFIRMATION. Test timeout.

### Contributor authoring

- **AC-106.6.** Author one contributor per qualifying AFFIRMATION with:
  ```
  origin      = "affirmation_pull"
  weight      = AFFIRM_PULL_WEIGHT_MAX = 0.03   (smaller than spec 104's 0.05)
  sign        = +1 if direction == "up" else -1
  source_memory_id = <affirmation memory_id>
  target_facet     = <facet name>
  ```
  Authored via the activation-graph write path (spec 25) with contributor-audit entry. Test weight, sign, origin, and audit.
- **AC-106.7.** Per-dream cap `AFFIRM_PULL_PER_DREAM_MAX = 3`. Test the cap.
- **AC-106.8.** Authoring subject to spec 40's facet-drift budget; a proposed contributor that would push the week's cumulative Δ past the cap is skipped (not trimmed). Test the skip.

### Contradicting AFFIRMATIONs (symmetric negative)

- **AC-106.9.** Detect contradicting AFFIRMATIONs by running a pairwise reflector check ("do these two AFFIRMATIONs take opposing stances on the same topic? yes/no") over AFFIRMATIONs sharing a topic cluster (embedding similarity `≥ 0.75`). When contradictions are found, author opposing contributors (same weight magnitude, opposite signs on the relevant facet). Test both the detection and the symmetric authoring.
- **AC-106.10.** Adversarial test: inject an AFFIRMATION contradicting a pre-existing one (same topic, opposing stance). Run the phase. Assert that two opposing contributors are authored on the same target facet, summing to net-zero immediate impact. Test this specifically.

### Cumulative-shift surfacing

- **AC-106.11.** Track cumulative shift per `(self_id, facet)` from `origin = "affirmation_pull"`. When cumulative shift on any one facet exceeds `AFFIRM_PULL_OPERATOR_SURFACE_THRESHOLD = 0.10`, surface a pending item to the operator review gate (spec 46) with rationale listing all contributing AFFIRMATIONs. Test the threshold trigger and the gate enqueue.
- **AC-106.12.** Cumulative shift is measured over a rolling 30-day window so the surfacing doesn't fire on ancient accumulated shift. Test the window.

### Observability

- **AC-106.13.** Prometheus counters: `turing_affirm_pull_authored_total{self_id,facet,direction}`, `turing_affirm_pull_skipped_budget_total{self_id,facet}`, `turing_affirm_pull_contradictions_total{self_id}`. Test counters.

## Implementation

```python
# dreaming/phases/affirmation_pull.py

AFFIRM_PULL_STABILITY_MIN_SESSIONS: int = 4
AFFIRM_PULL_WEIGHT_MAX: float = 0.03
AFFIRM_PULL_PER_DREAM_MAX: int = 3
AFFIRM_PULL_REFLECTOR_TIMEOUT_SEC: int = 10
AFFIRM_PULL_OPERATOR_SURFACE_THRESHOLD: float = 0.10


async def run(dream_ctx, repo, llm, graph, drift_budget, review_gate) -> int:
    if dream_ctx.smoke_mode:
        return 0
    stable = repo.stable_affirmations(
        self_id=dream_ctx.self_id,
        min_sessions=AFFIRM_PULL_STABILITY_MIN_SESSIONS,
    )
    authored = 0
    for aff in stable:
        if authored >= AFFIRM_PULL_PER_DREAM_MAX:
            break
        decision = await _reflect_with_timeout(
            llm, aff, AFFIRM_PULL_REFLECTOR_TIMEOUT_SEC,
        )
        if decision is None:
            continue
        sign = +1 if decision["direction"] == "up" else -1
        delta = AFFIRM_PULL_WEIGHT_MAX * sign
        if not drift_budget.admit(dream_ctx.self_id, decision["facet"], delta):
            continue
        graph.author_contributor(
            self_id=dream_ctx.self_id,
            source_memory_id=aff.memory_id,
            target_facet=decision["facet"], weight=delta,
            origin="affirmation_pull",
            rationale=f"AFFIRMATION stable for {aff.sessions_seen} sessions",
        )
        authored += 1
    _author_contradictions(repo, llm, graph, drift_budget, dream_ctx.self_id)
    _surface_over_threshold(
        repo, review_gate, dream_ctx.self_id,
        AFFIRM_PULL_OPERATOR_SURFACE_THRESHOLD,
    )
    return authored
```

## Open questions

- **Q106.1.** Stability threshold 4 sessions ≈ 4 weeks at weekly dreams (or faster at higher frequencies). Too slow? Too fast? Tune on real cadence.
- **Q106.2.** Weight 0.03 is smaller than spec 104 to reflect "prospective < retrospective" epistemic weight. The ratio (3:5) is intuitive; not tuned.
- **Q106.3.** Contradiction detection via pairwise reflector is O(n²) in stable AFFIRMATIONs; clustering by topic embedding (already required at 0.75) is the primary bound. Worth benchmarking once we see AFFIRMATION counts.
- **Q106.4.** When an operator rejects a surfaced accumulated-shift item, what happens to already-authored contributors? Options: retract all (symmetric with spec 63's dismissal path) or freeze and block further authoring. Deferred.
