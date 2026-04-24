# Spec 105 — Counterfactual personality simulation

*A weekly dreaming phase: for top-K high-surprise events, counterfactually simulate "if facet F had been Δ higher at decision time, would the outcome have been different?" When the same (facet, direction) wins across ≥N events under RULER judging, propose a facet adjustment to the operator review gate. The self can want to change; it cannot self-adjust.*

**Depends on:** [dreaming.md](./dreaming.md), [personality.md](./personality.md), [facet-drift-budget.md](./facet-drift-budget.md), [operator-review-gate.md](./operator-review-gate.md), [litellm-provider.md](./litellm-provider.md), [weekly-self-dialogue-ritual.md](./weekly-self-dialogue-ritual.md).

---

## Current state

Spec 104 lets dreaming author small attribution contributors into facets from past trace events. But the self has no way to ask the forward question: *"would I prefer to be different?"* The weekly HEXACO-24 retest (spec 23) adjusts facets via external self-report at 0.25 blend — a mechanism that reacts to present self-perception, not hypothetical future selves. Nothing today supports deliberate, simulated, operator-reviewed personality change.

## Target

A separate dreaming phase, scheduled weekly (not every dream), coinciding with the weekly HEXACO-24 retest and the weekly self-dialogue ritual (spec 94). For each of the top-K highest-surprise events since the last run, the phase runs counterfactuals: "if facet F had been Δ higher at decision time, would the outcome have been different?" Each counterfactual is judged by a two-judge minimum RULER panel. When the same `(facet, direction)` wins across ≥N distinct events, a facet-adjustment **proposal** is emitted into the operator review gate as a pending contributor. Operator accepts or rejects; rejection mints a LESSON-tier rationale. Dreaming-phase contribution is hard-capped at ≤30% of the weekly retest weight so retest remains the dominant signal.

## Acceptance criteria

### Scheduling and gating

- **AC-105.1.** Phase runs on a weekly cadence, aligned to the same weekday as the HEXACO-24 retest. Test alignment.
- **AC-105.2.** Disabled in `smoke_mode`. Test the disable.
- **AC-105.3.** Max one facet-move proposal per simulation session (even if multiple `(facet, direction)` pairs would qualify, the strongest single wins). Test the cap.
- **AC-105.4.** Hard ceiling: `CPS_DREAM_CONTRIBUTION_SHARE_MAX = 0.30` — the weekly contribution from this phase to any given facet cannot exceed 30% of that week's HEXACO-24 retest contribution on the same facet. Test with a stub retest weight.

### Event selection

- **AC-105.5.** Candidate events are `CPS_TOP_K = 5` highest-surprise completed events since the previous weekly run. Test the selection and bound.
- **AC-105.6.** Events already used as source data in a prior week's proposal are excluded to prevent re-stacking (track via metadata flag `cps_used = true`). Test the exclusion.

### Counterfactual simulation

- **AC-105.7.** Simulation granularity: for each event, simulate both `Δ = +0.5` and `Δ = -0.5` on each facet cited by that event's trace (facets come from spec 104's attribution metadata; fall back to all 24 if none). Test both directions.
- **AC-105.8.** Each counterfactual is judged by ≥2 independent RULER panels (two LLM judges, different seed/temperature) via spec 19 `complete()`. A counterfactual `"wins"` a facet direction when both judges agree the counterfactual outcome scores higher than the actual outcome. Test the two-judge requirement and the agreement rule.
- **AC-105.9.** Tie handling: if judges disagree, that counterfactual doesn't count. Test disagreement path.

### Proposal authoring

- **AC-105.10.** A proposal is authored only when the same `(facet, direction)` wins across `CPS_AGREEING_EVENTS_MIN = 3` distinct events in the session. Test the threshold.
- **AC-105.11.** The proposal is a pending contributor in the operator review gate queue (spec 46) with `origin = "counterfactual_personality_simulation"`, `weight = 0` (placeholder — operator sets effective weight on accept), `rationale` listing the N agreeing events' memory_ids. Test the queue entry and rationale.
- **AC-105.12.** Accepted proposals subject to facet-drift budget (spec 40) on the accept step — an accept that would bust the budget is auto-rejected with a log line. Test the bust path.
- **AC-105.13.** Rejected proposals mint a LESSON-tier memory with `source = I_DID`, `content = "I wanted to shift {facet} {direction} based on {n} events but the operator declined."`, linked to the rejected contributor. Test rejection path and LESSON content.

### Observability

- **AC-105.14.** Dream marker records `cps_proposal_count`, `cps_proposed_facet`, `cps_agreeing_events`. Test the marker.
- **AC-105.15.** Prometheus gauge `turing_cps_pending_proposals{self_id}`; counter `turing_cps_accepted_total{self_id,facet,direction}`, `turing_cps_rejected_total{self_id,facet,direction}`. Test metrics.

## Implementation

```python
# dreaming/phases/counterfactual_personality_simulation.py

CPS_TOP_K: int = 5
CPS_AGREEING_EVENTS_MIN: int = 3
CPS_DREAM_CONTRIBUTION_SHARE_MAX: float = 0.30


async def run_weekly(dream_ctx, repo, llm, review_gate, drift_budget) -> str | None:
    if dream_ctx.smoke_mode:
        return None
    events = repo.top_surprise_since(
        self_id=dream_ctx.self_id,
        since=dream_ctx.prev_weekly_run,
        limit=CPS_TOP_K,
        exclude_flag="cps_used",
    )
    scoreboard: dict[tuple[str, str], list[str]] = {}
    for ev in events:
        facets = ev.metadata.get("attributed_facets") or ALL_HEXACO_24
        for facet in facets:
            for direction, delta in (("up", +0.5), ("down", -0.5)):
                j1 = await _ruler_judge(llm, ev, facet, delta, seed=1)
                j2 = await _ruler_judge(llm, ev, facet, delta, seed=2, temp=0.8)
                if j1.wins and j2.wins:
                    scoreboard.setdefault((facet, direction), []).append(ev.memory_id)
        repo.mark_cps_used(ev.memory_id)
    winners = [
        (k, v) for k, v in scoreboard.items() if len(v) >= CPS_AGREEING_EVENTS_MIN
    ]
    if not winners:
        dream_ctx.marker["cps_proposal_count"] = 0
        return None
    (facet, direction), cited = max(winners, key=lambda kv: len(kv[1]))
    proposal_id = review_gate.enqueue_contributor(
        self_id=dream_ctx.self_id,
        target_facet=facet, direction=direction,
        origin="counterfactual_personality_simulation",
        rationale_events=cited,
    )
    dream_ctx.marker.update({
        "cps_proposal_count": 1,
        "cps_proposed_facet": facet,
        "cps_agreeing_events": len(cited),
    })
    return proposal_id
```

## Open questions

- **Q105.1.** `Δ = ±0.5` on a 1–5 HEXACO scale is substantial. Smaller Δ (0.25) might surface subtler effects but requires a stronger judge.
- **Q105.2.** Two-judge agreement is a floor, not a ceiling; a three-judge majority might reduce false positives. Cost tradeoff.
- **Q105.3.** `CPS_DREAM_CONTRIBUTION_SHARE_MAX = 0.30` is enforced at the accept step, not the propose step — this lets operators see and reason about over-budget proposals. If that leaks too much signal noise, shift to propose-step enforcement.
- **Q105.4.** The operator review gate (spec 46) is the sole accept authority. Alternate mechanisms (e.g. auto-accept if ≥5 events agree and budget has headroom) are deferred until operator trust is established.
