# Spec 104 — Dream-phase facet attribution

*During dreaming — after LESSON consolidation, before non-durable pruning — walk recent REGRETs and ACCOMPLISHMENTs, ask a sandboxed reflector which facet most plausibly caused the outcome, and — when ≥2 trace events cite the same facet — author a small `dream`-origin contributor edge into that facet through the activation graph, subject to the weekly facet-drift budget.*

**Depends on:** [dreaming.md](./dreaming.md), [activation-graph.md](./activation-graph.md), [facet-drift-budget.md](./facet-drift-budget.md), [personality.md](./personality.md), [operator-review-gate.md](./operator-review-gate.md), [memory-mirroring.md](./memory-mirroring.md).

---

## Current state

Facet values (HEXACO-24, spec 23) are set by the weekly 20-item retest at 0.25 blend. The activation graph (spec 25) has edges with origins `"rule"`, `"operator"`, and `"self_narrative"`. There is no path by which dreaming — the offline reflection loop — can adjust personality. Consequently, when the self accumulates two REGRETs that both clearly stem from high-facet-F behavior, nothing in the system nudges facet F downward.

## Target

A new dreaming phase — `"facet_attribution"` — positioned after `"lesson_consolidation"` and before `"non_durable_pruning"`. Walks the period's REGRETs and ACCOMPLISHMENTs, runs each through a sandboxed Python reflector (an ACE-style code-executable reflector LLM) that returns a single-facet attribution. When two or more trace events attribute the same `(facet, direction)`, author a `dream`-origin contributor edge with tiny weight into that facet. The facet-drift budget (spec 40) applies unchanged — if the week's Δ cap is reached, the phase stops authoring. The attribution is `I_DID` (the self actually witnessed the trajectory) and mirrors to episodic memory as a LESSON per spec 32. First dreaming mechanism that touches personality; proposed carefully to minimize cargo-cult blame.

## Acceptance criteria

### Phase insertion and gating

- **AC-104.1.** New dreaming phase `"facet_attribution"` registered immediately after `"lesson_consolidation"` and immediately before `"non_durable_pruning"`. Test the phase ordering and test a guard that fails loudly if another spec perturbs placement.
- **AC-104.2.** Phase disabled when `smoke_mode = True`. Test the disable.
- **AC-104.3.** Per-dream cap `FACET_ATTRIBUTION_PER_DREAM_MAX = 5` — at most five contributors authored per session. Test the cap.

### Trace selection and reflector call

- **AC-104.4.** Candidate traces are REGRETs and ACCOMPLISHMENTs from the current dream period, deduplicated by `request_hash` (forensic tag, spec 39). Test dedup.
- **AC-104.5.** For each candidate, invoke a sandboxed reflector (code-executable Python sandbox with `SANDBOX_TIMEOUT_SEC = 30` and no network) asking: *"Which single HEXACO-24 facet most plausibly caused this outcome, and in which direction (up/down)?"* Output must be a JSON object `{"facet": <one of 24>, "direction": "up"|"down"}`; malformed output is treated as no-attribution. Test timeout, malformed output, and a happy-path attribution.
- **AC-104.6.** Reflector runs with the LLM provider from spec 19 (`complete()`); the Python sandbox executes any code the reflector emits but returns only the JSON decision. Test the pipe.

### Contributor authoring

- **AC-104.7.** A `(facet, direction)` is authored only if ≥2 traces in the current period cite the same pair (prevents one-shot cargo-cult blame). Test the 2-citation rule.
- **AC-104.8.** Weight per authored contributor `FACET_ATTRIBUTION_WEIGHT_MAX = 0.05`, with direction sign. `origin = "dream"`. The edge is inserted via the activation-graph write path (spec 25) and recorded in the contributor audit. Test the weight, sign, origin, and audit.
- **AC-104.9.** Before authoring, check spec 40's facet-drift budget. If this week's cumulative Δ on the target facet, including this proposed edge, would exceed the weekly cap, the author is skipped (not trimmed — skipped entirely) and a log line is emitted. Test the cap and the skip.
- **AC-104.10.** Each authored contributor routes through the operator review gate (spec 46) and surfaces in the weekly digest as a pending contributor item. Test the gate entry.

### Memory side effects

- **AC-104.11.** Each authored contributor produces a LESSON memory via memory-mirroring (spec 32) with `source = I_DID`, `content = "In dreaming I attributed {facet} ({direction}) from {n_citations} trace events: {memory_ids}"`. Test the mirror.
- **AC-104.12.** Dream session marker includes `attribution_count: int` and `attributed_facets: list[str]`. Test marker fields.

### Observability

- **AC-104.13.** Prometheus counter `turing_dream_facet_attributions_total{self_id,facet,direction}` increments on author. `turing_dream_facet_attribution_skipped_budget_total{self_id,facet}` on budget-skip. Test both.

## Implementation

```python
# dreaming/phases/facet_attribution.py

FACET_ATTRIBUTION_PER_DREAM_MAX: int = 5
FACET_ATTRIBUTION_WEIGHT_MAX: float = 0.05
SANDBOX_TIMEOUT_SEC: int = 30


async def run(dream_ctx, repo, llm, sandbox, graph, drift_budget) -> int:
    if dream_ctx.smoke_mode:
        return 0
    traces = repo.period_regrets_and_accomplishments(
        self_id=dream_ctx.self_id, period=dream_ctx.period,
    )
    traces = _dedup_by_request_hash(traces)
    votes: dict[tuple[str, str], list[str]] = {}
    for t in traces:
        decision = await _reflect(llm, sandbox, t)
        if decision is None:
            continue
        key = (decision["facet"], decision["direction"])
        votes.setdefault(key, []).append(t.memory_id)
    authored = 0
    for (facet, direction), cited in votes.items():
        if authored >= FACET_ATTRIBUTION_PER_DREAM_MAX:
            break
        if len(cited) < 2:
            continue
        delta = FACET_ATTRIBUTION_WEIGHT_MAX * (+1 if direction == "up" else -1)
        if not drift_budget.admit(dream_ctx.self_id, facet, delta):
            logger.info("facet-drift budget skip for %s", facet)
            continue
        contrib_id = graph.author_contributor(
            self_id=dream_ctx.self_id, target_facet=facet,
            weight=delta, origin="dream",
            rationale=f"dream attribution from {len(cited)} traces",
        )
        repo.mirror_lesson(
            self_id=dream_ctx.self_id,
            content=(
                f"In dreaming I attributed {facet} ({direction}) from "
                f"{len(cited)} trace events: {cited}"
            ),
        )
        dream_ctx.review_gate.enqueue_contributor(contrib_id)
        authored += 1
    dream_ctx.marker["attribution_count"] = authored
    return authored
```

## Open questions

- **Q104.1.** Sandbox mechanism is ACE-style; details of the Python sandbox runtime are out of scope for this spec. Safe default: `RestrictedPython` with no I/O.
- **Q104.2.** Two-citation rule is strict; a softer rule (e.g. one citation with reflector confidence ≥ 0.9) might surface more. Deferred until we see signal-to-noise in real data.
- **Q104.3.** Attribution always flows up OR down; there's no "neutral." A reflector that wants to decline should return `null` (treated as no-attribution). Documented.
- **Q104.4.** Weight 0.05 per contributor × 5 per session = 0.25 theoretical weekly max from dream attribution alone. Spec 40's cap must be ≥ 0.25 or the phase will chronically budget-skip — cross-check when tuning.
