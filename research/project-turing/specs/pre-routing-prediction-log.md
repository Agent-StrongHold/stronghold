# Spec 102 — Pre-routing prediction log

*Before dispatch, first-person-simulate each candidate specialist's outcome, RULER-judge the simulation, log each as I_IMAGINED with a waypoint trace of retrieved memories, then — after the actual outcome arrives — diff predicted vs actual and mint a calibration LESSON when the gap is large.*

**Depends on:** [prospective-simulation.md](./prospective-simulation.md), [litellm-provider.md](./litellm-provider.md), [retrieval.md](./retrieval.md), [bitemporal-perspective-replay.md](./bitemporal-perspective-replay.md), [prospection-accuracy-detector.md](./prospection-accuracy-detector.md).

---

## Current state

Spec 60 (prospective simulation) describes how, before dispatch, the self imagines outcomes for candidate specialists. But the simulations are transient — they influence the routing decision and then vanish. There is no persisted record of what the self predicted, no later comparison against what actually happened, and no mechanism to mint a LESSON when the self was badly miscalibrated. Prospection accuracy (spec 66) measures accuracy at the aggregate level but has no per-request trail.

## Target

Each pre-routing simulation is persisted as an `I_IMAGINED` memory with a RULER score and a **waypoint trace** (list of `memory_id`s that the retrieval layer surfaced to inform the prediction). After dispatch completes and the actual outcome is scored, the system diffs predicted vs actual score. When `|Δ| ≥ threshold`, a LESSON (source `I_DID` — the self actually lived the mismatch) is minted capturing specialist, predicted score, actual score, and the waypoint trace of memories that misled it. To control cost, pre-routing simulation is gated to request shapes that are semantically adjacent to a recent REGRET.

## Acceptance criteria

### Gating

- **AC-102.1.** Gate on REGRET-adjacency: a pre-routing simulation fires only when the incoming request's embedding has cosine similarity ≥ `PREROUTING_GATE_SIMILARITY = 0.7` to at least one memory in the top-50 most-recent REGRETs for this self. Test the gate admits REGRET-adjacent shapes and rejects otherwise.
- **AC-102.2.** When the gate rejects, routing proceeds unchanged and no `I_IMAGINED` is written. Test no memory write and no metric increment happens on rejection.
- **AC-102.3.** Gating is bypassed when `PREROUTING_FORCE = true` (operator override for eval runs). Test the override.

### Simulation and RULER judge

- **AC-102.4.** For each candidate specialist returned by the router, run one first-person simulation via the spec 19 `complete()` provider. Prompt template: `"As {self.name}, if I route this request to {specialist}, what outcome do I predict?"`. Test one simulation per candidate.
- **AC-102.5.** Each simulation's output is scored by an LLM RULER judge (spec 19 `complete()` with a fixed judge prompt) on a `[0.0, 1.0]` scale. Test the score is persisted as float.
- **AC-102.6.** Simulation timeout `PREROUTING_SIM_TIMEOUT_SEC = 8` per candidate; timeouts are recorded with score `None` and do not block dispatch. Test timeout handling.

### Memory write

- **AC-102.7.** Each simulation produces one `I_IMAGINED` memory written via the standard write path (spec 18):
  ```
  source = I_IMAGINED
  tier   = OBSERVATION (starts at OBSERVATION, will never reach durable — I_IMAGINED rule)
  content = "If I route to {specialist}, I predict: {simulation_output}"
  metadata = {
      kind: "prerouting_prediction",
      specialist: <name>,
      ruler_score: <float or null>,
      waypoint_trace: [<memory_id>, ...],
      request_hash: <forensic>,
      perception_tool_call_id: <forensic>,
  }
  ```
  Test the write and tag assertions.
- **AC-102.8.** `waypoint_trace` lists the `memory_id`s that the spec 16 retrieval layer surfaced as context for the simulation (max 10). Empty list if retrieval returned nothing. Test the trace is populated.
- **AC-102.9.** I_IMAGINED predictions older than `PREROUTING_IMAGINED_TTL_DAYS = 30` are soft-deleted by a background detector. Test cleanup runs and removes expired entries; durable tiers are untouched because I_IMAGINED cannot reach them.

### Post-dispatch diff

- **AC-102.10.** When the actual dispatch completes and its outcome is scored (reuse whatever outcome scorer spec 60 and spec 66 already use), diff `|actual_score - predicted_score|`. If `|Δ| ≥ PREROUTING_MISMATCH_THRESHOLD = 0.3`, mint a LESSON with `source = I_DID`, `content = f"I predicted {predicted:.2f} for {specialist} but got {actual:.2f}. The memories I leaned on were {waypoint_trace}."`. Test LESSON write.
- **AC-102.11.** The LESSON's metadata carries the original `I_IMAGINED` memory_id so the two are cross-linked. Test the link is bidirectional (LESSON → imagined, imagined metadata gets `mismatch_lesson_id` set). Durable LESSON write respects I_DID requirement.
- **AC-102.12.** When `|Δ| < threshold`, no LESSON is minted. Test the negative case.

### Observability

- **AC-102.13.** Prometheus metric `turing_prerouting_mean_surprise{self_id,specialist}` updates on each post-dispatch diff. Mean surprise per specialist is the per-specialist EMA (α=0.2) of `|Δ|`. Test metric updates and per-specialist isolation.
- **AC-102.14.** `stronghold self digest` surfaces the three specialists with highest mean-surprise in the last 7 days alongside how many mismatches fired. Test the digest line.

## Implementation

```python
# prerouting/prediction_log.py

PREROUTING_GATE_SIMILARITY: float = 0.7
PREROUTING_SIM_TIMEOUT_SEC: int = 8
PREROUTING_MISMATCH_THRESHOLD: float = 0.3
PREROUTING_IMAGINED_TTL_DAYS: int = 30


async def run_prerouting(
    request, candidates, self_id, repo, llm, retriever
) -> list[Prediction]:
    if not _gate(request, self_id, repo):
        return []
    predictions: list[Prediction] = []
    for specialist in candidates:
        waypoints = retriever.retrieve_for_request(request, self_id, k=10)
        sim = await _simulate(llm, self_id, specialist, request, waypoints)
        score = await _ruler_judge(llm, sim)
        mem_id = repo.write_memory(
            self_id=self_id,
            source="I_IMAGINED",
            tier="OBSERVATION",
            content=f"If I route to {specialist}, I predict: {sim}",
            metadata={
                "kind": "prerouting_prediction",
                "specialist": specialist,
                "ruler_score": score,
                "waypoint_trace": [w.memory_id for w in waypoints],
                "request_hash": request.hash,
                "perception_tool_call_id": request.perception_tool_call_id,
            },
        )
        predictions.append(Prediction(mem_id, specialist, score))
    return predictions


async def post_dispatch_diff(prediction, actual_score, repo, self_id) -> str | None:
    if prediction.score is None:
        return None
    delta = abs(actual_score - prediction.score)
    if delta < PREROUTING_MISMATCH_THRESHOLD:
        return None
    lesson_id = repo.write_memory(
        self_id=self_id,
        source="I_DID",
        tier="LESSON",
        content=(
            f"I predicted {prediction.score:.2f} for {prediction.specialist} "
            f"but got {actual_score:.2f}. The memories I leaned on were "
            f"{prediction.waypoint_trace}."
        ),
        metadata={"from_prediction": prediction.memory_id, "delta": delta},
    )
    repo.set_mismatch_lesson(prediction.memory_id, lesson_id)
    return lesson_id
```

## Open questions

- **Q102.1.** Gate threshold 0.7 is conservative; may cause most requests to skip simulation. Revisit once traffic data is available.
- **Q102.2.** RULER judge shares the same LLM provider as the simulator — risk of shared-blind-spot bias. Dual-judge variant is an option but doubles cost.
- **Q102.3.** Mean-surprise EMA α=0.2 favors recent signal; a per-specialist configurable α may be needed for slow-moving specialists.
- **Q102.4.** Cleanup TTL 30 days is arbitrary — long enough to support retrospective analysis, short enough to keep the table bounded. Tune once we know table growth rate.
