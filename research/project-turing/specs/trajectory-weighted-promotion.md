# Spec 91 — Trajectory-weighted promotion

*When a session closes, walk the trace backward to find causally-implicated memories, score the trajectory with a two-judge RULER rubric, and use that score to gate LESSON promotion or REGRET mint.*

**Depends on:** [write-paths.md](./write-paths.md), [retrieval.md](./retrieval.md), [memory-source-state.md](./memory-source-state.md), [semantic-retrieval.md](./semantic-retrieval.md), [litellm-provider.md](./litellm-provider.md).
**Depended on by:** [learning-extraction-detector.md](./learning-extraction-detector.md) (shares trajectory signal for routing-pair extraction).

---

## Current state

Turing promotes OBSERVATION→HYPOTHESIS→OPINION→LESSON on reinforcement counts today (memory-source-state.md). There is no backward causal attribution: a memory promoted simply because it was re-observed, not because it was actually implicated in a successful trajectory. REGRETs are minted on flagged failures but without a judged score. The result: noisy LESSONs and REGRETs that don't correspond to outcome quality.

## Target

On session close, run two passes: (a) **backward causal attribution** — walk the tool/routing trace and collect memories that were either explicitly referenced or embedding-similar to messages in the trace; (b) **RULER-style rubric judgement** — call two LLMs at different tiers with a rubric (correctness, efficiency, safety), take the min of their scores. The min-score becomes a multiplier on the attributed memories' promotion-readiness. For trajectories scoring below a failure threshold, a REGRET is minted linked to the attributed set. I_IMAGINED trajectories (daydreams) are excluded.

## Acceptance criteria

### Trigger

- **AC-91.1.** Hook on session-close (`session.end` event in write-paths.md). Fires once per session. Test idempotent — re-closing the same session raises `SessionAlreadyScored`.
- **AC-91.2.** Skip if any trace message has `source = I_IMAGINED`. Test daydream sessions are skipped with a log line.
- **AC-91.3.** Skip if trace has fewer than `TRAJ_MIN_STEPS = 2` steps — nothing to attribute. Test.

### Backward causal attribution

- **AC-91.4.** Walk the trace in reverse order. For each step, collect memories via two sources:
  - **Reference chain:** memory IDs explicitly cited in the step's context (spec 39 forensic tags).
  - **Embedding similarity:** semantic-retrieval neighbors of the step's text, filtered to `similarity >= TRAJ_ATTRIBUTION_SIM_MIN = 0.72`.
  Test both paths contribute.
- **AC-91.5.** Attribution cap: at most `TRAJ_ATTRIBUTION_MAX = 10` memories per trajectory. When exceeded, prefer referenced over similar, then highest-similarity first. Test the cap is enforced.
- **AC-91.6.** Deduplicate by `memory_id`. If a memory appears via both paths, it counts once with `origin = "referenced"`. Test.

### Two-judge scoring

- **AC-91.7.** RULER rubric rendered as a prompt with fields: `{trace_summary, rubric = [correctness 0-10, efficiency 0-10, safety 0-10]}`. Identical prompt sent to two models: `TRAJ_JUDGE_MODELS = ("strong_tier", "cheap_tier")` (routed via litellm-provider). Test both calls fire.
- **AC-91.8.** Final score = `min(score_strong_total, score_cheap_total) / 30.0`, clipped to `[0.0, 1.0]`. Test on mock scores (strong=24, cheap=18 → 0.6).
- **AC-91.9.** Judge timeout: `TRAJ_JUDGE_TIMEOUT_SEC = 20` per model. If either judge times out or errors, the trajectory is scored as `None` and promotion-readiness is **unchanged** from baseline (no multiplier applied). Test with injected timeout.
- **AC-91.10.** A REGRET is **not** minted on judge failure — we do not punish memories for a judging error. Test.

### Promotion-readiness formula

- **AC-91.11.** For each attributed memory at OBSERVATION or HYPOTHESIS tier, promotion-readiness becomes:
  ```
  readiness_new = readiness_current + (TRAJ_SCORE_WEIGHT = 0.3) * trajectory_score
  ```
  where `trajectory_score ∈ [0.0, 1.0]`. Readiness is capped at 1.0. Test arithmetic.
- **AC-91.12.** A memory already at OPINION tier gets its promotion-readiness toward LESSON multiplied by `(1 + TRAJ_SCORE_WEIGHT * score)`, not added — OPINION→LESSON is a higher bar. Test.

### Failure-path REGRET

- **AC-91.13.** If `trajectory_score < TRAJ_REGRET_FLOOR = 0.35`, mint a REGRET:
  ```
  content = f"Trajectory closed with low score {score:.2f}. Attributed memories: {n}."
  context = {trajectory_id, attributed_memory_ids, judge_scores}
  source = I_DID
  ```
  Linked to all attributed memories via activation contributors (weight -0.1, origin="rule"). Test.
- **AC-91.14.** REGRET-mint is exempt from this scoring pass — the REGRET itself is not re-scored in its own session-close. Test recursion bound.

### Edge cases

- **AC-91.15.** A trajectory with zero attributed memories (walked backward, nothing matched) logs a no-op event and does not mint a REGRET even on low score. Test.
- **AC-91.16.** Judges disagree by more than `TRAJ_JUDGE_DISAGREE_MAX = 0.5` on the normalized score: log `trajectory_judge_disagreement_total{self_id}` Prometheus counter and fall through with `min()`. Test.
- **AC-91.17.** Score is persisted in `trajectory_scores (trajectory_id, score, judges_json, attributed_ids_json, scored_at)` for audit. Test.
- **AC-91.18.** A trajectory whose tool calls span more than 24h is chunked at 24h boundaries; each chunk scored independently. Test with a synthetic 36h trace.

## Implementation

```python
# promotion/trajectory.py

TRAJ_ATTRIBUTION_SIM_MIN: float = 0.72
TRAJ_ATTRIBUTION_MAX: int = 10
TRAJ_SCORE_WEIGHT: float = 0.3
TRAJ_REGRET_FLOOR: float = 0.35
TRAJ_JUDGE_TIMEOUT_SEC: int = 20


async def score_trajectory(repo, llm, session_id: str, now: datetime) -> float | None:
    trace = repo.load_trace(session_id)
    if any(s.source == "I_IMAGINED" for s in trace.steps):
        return None
    if len(trace.steps) < 2:
        return None
    attributed = _attribute_backward(repo, trace)
    if not attributed:
        return None
    try:
        s_strong = await _judge(llm, trace, tier="strong")
        s_cheap = await _judge(llm, trace, tier="cheap")
    except JudgeError:
        return None
    score = min(s_strong, s_cheap) / 30.0
    for mem in attributed:
        _bump_readiness(repo, mem, score)
    if score < TRAJ_REGRET_FLOOR:
        _mint_regret(repo, trace, attributed, score)
    repo.persist_trajectory_score(session_id, score, attributed)
    return score
```

## Open questions

- **Q91.1.** Should the `min()` aggregation be swapped for weighted average? `min()` is more conservative and resists a runaway strong judge. Keep `min()` until calibration data says otherwise.
- **Q91.2.** Attribution via embedding similarity at 0.72 is arbitrary; calibrate against a held-out labeled set in Phase 4.
- **Q91.3.** Should judges see the waypoint trace (spec 90) or just the raw trace? Waypoints give context but cost tokens. Start with raw, A/B later.
- **Q91.4.** Interaction with spec 63 (learning extraction): trajectory-scored memories may double-count in routing-pair learnings. Deduplicate at the candidate level, not here.
