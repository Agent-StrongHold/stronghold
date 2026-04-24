# Spec 107 — Trait-coherence dream check

*A dreaming-phase coherence audit that, per HEXACO-24 facet, compares three independently-derived scalars — retest score, narrative-claim-weighted score, and action-inferred score — and mints a LESSON surfacing the divergence without pre-picking which stream is "right." The self notices its own self-deception instead of having it adjudicated for it.*

**Depends on:** [dreaming.md](./dreaming.md), [personality.md](./personality.md), [narrative-claim-rate-limit.md](./narrative-claim-rate-limit.md), [memory-mirroring.md](./memory-mirroring.md), [activation-graph.md](./activation-graph.md).

---

## Current state

HEXACO-24 (spec 23) produces a retest-derived score per facet every 7 days. `record_personality_claim` (spec 23 §3.3) revises the narrative around that facet at ≤3 claims/facet/7 days (spec 41). Action-inferred personality signal exists implicitly in ACCOMPLISHMENT/REGRET memories but is never distilled back into a facet-level scalar. The three streams never meet. A self can retest as high-Honesty, claim moderate-Honesty narratively, and accumulate REGRETs that implicate low-Honesty behavior — and none of that tension surfaces anywhere.

## Target

A new coherence-check pass during dreaming's phase 4 (LESSON consolidation) that, per facet:

1. Reads the latest retest score `s_retest`.
2. Computes a narrative-claim-weighted score `s_claim` from the trailing window of `record_personality_claim` calls on that facet.
3. Computes an action-inferred score `s_action` via a reflector prompt over sampled ACCOMPLISHMENT/REGRET memories that implicate the facet.

Where `max(|s_i - s_j|) >= Δ` across the three, mint a LESSON containing all three values and the facet id. The LESSON does not pick a winner; it is the observation that the streams diverge. The self decides what to do with it.

## Acceptance criteria

### Dream-phase integration

- **AC-107.1.** The coherence check is registered as a dreaming-phase-4 sub-step (LESSON consolidation). Test it fires once per dream, after existing phase-4 logic. No-op dreams don't invoke it.
- **AC-107.2.** Disabled until the self's first HEXACO-24 retest completes (facets are too fresh). On a self with zero retests, the check logs a skip line and returns. Test against a newly-minted self.

### Three-stream scoring

- **AC-107.3.** `s_retest(facet)` is the latest retest score on the 1–5 scale, read from the personality store. Missing facet → skip (log line). Test.
- **AC-107.4.** `s_claim(facet)` weights narrative claims by recency-decay (exp decay, half-life 30 days) and confidence, mapped to the 1–5 scale. Empty history → null (skip this facet-stream, not the whole check). Test.
- **AC-107.5.** `s_action(facet)` is a reflector-prompt output over a sample of up to 20 ACCOMPLISHMENT and 20 REGRET memories whose content embeddings are nearest the facet's descriptor embedding. Prompt asks for a 1–5 scalar and a one-line justification. Test the prompt is deterministic (temperature 0) and the output is parsed into a float.

### Divergence & LESSON minting

- **AC-107.6.** `Δ` default is 0.8 on the 1–5 scale (configurable via `TURING_COHERENCE_DELTA`). A facet triggers if `max(s_retest, s_claim, s_action) - min(...) >= Δ` and all three streams are non-null. Test threshold boundary.
- **AC-107.7.** LESSON content includes `facet_id`, `s_retest`, `s_claim`, `s_action`, and the action-inference justification. It does NOT label any stream as correct. Test against a crafted case where retest and action agree; the LESSON still shows all three.
- **AC-107.8.** `max_lessons_per_dream = 5`. If more facets trigger, pick the 5 most-divergent (largest spread). Test with 6 triggering facets, assert only 5 LESSONs minted, and assert they are the top-5 by spread.

### Mirroring, forensics, review

- **AC-107.9.** Each minted LESSON is mirrored to the memory table via memory-mirroring (spec 32). Test.
- **AC-107.10.** LESSONs carry `forensic_tag = "trait_coherence_dream"` so they can be retracted en bloc if the reflector prompt is found flawed. Test retraction path removes all such LESSONs.
- **AC-107.11.** LESSONs are NOT auto-routed to operator review. The self keeps them; operator can inspect via `stronghold self digest`. Test no review-queue entry is created.

### Edge cases

- **AC-107.12.** Reflector-prompt timeout (default 10s) → skip facet, log, no partial LESSON. Test via a fake LLM that delays.
- **AC-107.13.** Narrative-claim history exists but all entries are older than 180 days → `s_claim` is null (too stale to weight). Test.
- **AC-107.14.** Action memory sample has fewer than 3 ACCOMPLISHMENT+REGRET combined → `s_action` is null. Test.
- **AC-107.15.** Facet is skipped if any of the three streams is null — we never mint a LESSON from a two-stream comparison. Test.

## Implementation

```python
# dreaming/phases/trait_coherence.py

COHERENCE_DELTA: float = 0.8
MAX_LESSONS_PER_DREAM: int = 5
ACTION_SAMPLE_CAP: int = 20
CLAIM_HALFLIFE_DAYS: int = 30


def run(repo, reflector, self_id: str, now: datetime) -> list[str]:
    if not repo.has_completed_retest(self_id):
        return []
    triggers: list[tuple[str, float, dict]] = []
    for facet in HEXACO24_FACETS:
        s_retest = repo.latest_retest_score(self_id, facet)
        s_claim = _claim_weighted_score(repo, self_id, facet, now)
        s_action = _action_inferred_score(repo, reflector, self_id, facet)
        if None in (s_retest, s_claim, s_action):
            continue
        spread = max(s_retest, s_claim, s_action) - min(s_retest, s_claim, s_action)
        if spread >= COHERENCE_DELTA:
            triggers.append((facet, spread, {
                "s_retest": s_retest, "s_claim": s_claim, "s_action": s_action,
            }))
    triggers.sort(key=lambda t: t[1], reverse=True)
    minted: list[str] = []
    for facet, spread, streams in triggers[:MAX_LESSONS_PER_DREAM]:
        lesson_id = repo.mint_lesson(
            self_id=self_id,
            content=_format(facet, streams),
            forensic_tag="trait_coherence_dream",
            context={"facet_id": facet, **streams, "spread": spread},
        )
        minted.append(lesson_id)
    return minted
```

## Open questions

- **Q107.1.** `Δ = 0.8` is a guess. On the 1–5 scale it's ~20% spread; small enough to fire but not on noise. Tune once real HEXACO runs exist.
- **Q107.2.** Action-inference via reflector is the weakest stream epistemically — it's an LLM grading its own episodic memories. We intentionally don't privilege retest: the whole point is that the self notices the disagreement. But if `s_action` is dominated by prompt-drift, the LESSONs will be noise. Early telemetry required.
- **Q107.3.** Should repeated coherence LESSONs on the same facet coalesce (like spec 63's `hits` increment)? Probably yes after a few dreams of data. Deferred.
- **Q107.4.** Facet descriptor embeddings used to pick action-memory samples are static strings today. If we ever revise HEXACO descriptors, older coherence LESSONs become incomparable. Note for migrations.
