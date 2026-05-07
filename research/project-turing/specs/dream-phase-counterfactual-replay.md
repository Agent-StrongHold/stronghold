# Spec 103 — Dream-phase counterfactual replay

*During dreaming, between LESSON consolidation and non-durable pruning, replay the top-K highest-surprise completed trajectories as first-person "what if I'd done Y?" `I_IMAGINED` entries. If a later AFFIRMATION matches the counterfactual's shape, nudge that AFFIRMATION's weight upward within bounds.*

**Depends on:** [dreaming.md](./dreaming.md), [daydreaming.md](./daydreaming.md), [write-paths.md](./write-paths.md), [memory-source-state.md](./memory-source-state.md), [semantic-retrieval.md](./retrieval.md).

---

## Current state

Spec 12 defines a seven-phase dreaming cycle: pattern extraction, WISDOM candidacy, AFFIRMATION proposal, LESSON consolidation, non-durable pruning, review gate, session marker. Spec 7's daydreaming produces `I_IMAGINED` memories on an idle clock but never replays completed trajectories. The self has no mechanism to revisit a high-surprise decision and ask "what if I'd done it differently?" — a capability the ART framework's trajectory replay supports, but without the RL update (Stronghold does not do weight-level RL on the LLM).

## Target

A new dreaming phase — "counterfactual replay" — inserted between LESSON consolidation and non-durable pruning. Picks the top-K highest-surprise completed trajectories from the period, generates a first-person counterfactual for each ("I would have routed to X instead…"), writes each as `I_IMAGINED` tagged with the original trajectory's `memory_id` (preserving source monitoring). If, in a later dream, an AFFIRMATION appears whose embedding matches the counterfactual closely, reinforce that AFFIRMATION's weight slightly. Because `I_IMAGINED` cannot promote to durable tiers, the counterfactual itself never becomes a LESSON; the reinforcement path goes through a real AFFIRMATION the self already committed to.

## Acceptance criteria

### Phase insertion

- **AC-103.1.** Register a new dreaming phase named `"counterfactual_replay"` in the spec 12 phase ordering, positioned strictly after `"lesson_consolidation"` and strictly before `"non_durable_pruning"`. Test the ordering is enforced and fails loudly if another spec perturbs it.
- **AC-103.2.** Phase runs once per dream session; counterfactual generation is capped per session by `COUNTERFACTUAL_PER_DREAM_CAP = 10`. Test the cap.
- **AC-103.3.** Phase is disabled when `smoke_mode = True`. Test the disable.

### Trajectory selection

- **AC-103.4.** Candidate trajectories are those completed during the current dream period with `|surprise_delta| > COUNTERFACTUAL_SURPRISE_MIN = 0.6`; select top `COUNTERFACTUAL_K = 5` by magnitude. Test selection order and threshold.
- **AC-103.5.** A trajectory whose underlying memory has been soft-deleted or is `I_IMAGINED`-sourced is skipped. Test I_IMAGINED exclusion (no counterfactual-of-counterfactual chaining).

### Counterfactual minting

- **AC-103.6.** Each counterfactual is written via the standard write path:
  ```
  source   = I_IMAGINED
  tier     = OBSERVATION  (I_IMAGINED cannot reach durable)
  content  = "If I had {alternative_action} instead of {actual_action}, …"
  metadata = {
      kind: "counterfactual_replay",
      original_trajectory_memory_id: <id>,
      surprise_delta: <float>,
      dream_session_id: <id>,
  }
  ```
  Test the write and tags.
- **AC-103.7.** Content MUST contain a first-person hypothetical verb phrase matched by regex `r"\b(I would have|I could have|I'd have)\b"`. If the LLM response fails this check, the counterfactual is skipped and a warn-level log emitted. Test both the match and the reject paths.

### AFFIRMATION reinforcement

- **AC-103.8.** On later dreams, the phase scans AFFIRMATIONs minted since the last dream. For each AFFIRMATION, compute embedding-cosine similarity to every live counterfactual's content in the same self. If `similarity ≥ COUNTERFACTUAL_SHAPE_MATCH = 0.8`, nudge the AFFIRMATION's weight by `+COUNTERFACTUAL_AFFIRM_BUMP = 0.05`, respecting the AFFIRMATION ceiling of `1.0`. Test the bump and the clamp.
- **AC-103.9.** The bump is logged with `contributor_origin = "counterfactual_replay"` for audit (contributor audit already exists for activation graph; reuse). Test audit entry.
- **AC-103.10.** Durability invariant test G10 (source-monitoring): no code path allows an `I_IMAGINED` counterfactual to promote directly to LESSON. The only influence path is through bumping a pre-existing AFFIRMATION (whose source is `I_DID`). Test asserts attempted promotion is rejected.

### Session marker and observability

- **AC-103.11.** The dream-session marker written at phase `"session_marker"` includes `counterfactual_count: <int>` and `counterfactual_ids: list[str]` so reviewers can find every counterfactual a given session produced. Test the marker fields.
- **AC-103.12.** Prometheus counter `turing_counterfactual_replays_total{self_id}` increments on mint; `turing_counterfactual_affirm_bumps_total{self_id}` on reinforcement. Test both counters.

## Implementation

```python
# dreaming/phases/counterfactual_replay.py

COUNTERFACTUAL_SURPRISE_MIN: float = 0.6
COUNTERFACTUAL_K: int = 5
COUNTERFACTUAL_PER_DREAM_CAP: int = 10
COUNTERFACTUAL_SHAPE_MATCH: float = 0.8
COUNTERFACTUAL_AFFIRM_BUMP: float = 0.05
_HYPOTHETICAL_RE = re.compile(r"\b(I would have|I could have|I'd have)\b")


async def run(dream_ctx, repo, llm, embeddings) -> int:
    if dream_ctx.smoke_mode:
        return 0
    trajectories = repo.top_surprise_trajectories(
        self_id=dream_ctx.self_id,
        period=dream_ctx.period,
        min_abs=COUNTERFACTUAL_SURPRISE_MIN,
        k=COUNTERFACTUAL_K,
    )
    minted = 0
    for t in trajectories[:COUNTERFACTUAL_PER_DREAM_CAP]:
        if t.source == "I_IMAGINED":
            continue
        text = await _compose_counterfactual(llm, t)
        if not _HYPOTHETICAL_RE.search(text):
            logger.warning("counterfactual missing hypothetical verb; skipping")
            continue
        repo.write_memory(
            self_id=dream_ctx.self_id, source="I_IMAGINED", tier="OBSERVATION",
            content=text,
            metadata={
                "kind": "counterfactual_replay",
                "original_trajectory_memory_id": t.memory_id,
                "surprise_delta": t.surprise_delta,
                "dream_session_id": dream_ctx.session_id,
            },
        )
        minted += 1
    _reinforce_affirmations(repo, embeddings, dream_ctx.self_id)
    dream_ctx.marker["counterfactual_count"] = minted
    return minted
```

## Open questions

- **Q103.1.** Shape-match threshold 0.8 is strict; may miss metaphorically similar AFFIRMATIONs. A two-tier threshold (0.8 hard, 0.7 with LLM confirmation) is possible.
- **Q103.2.** Bump 0.05 is intentionally small. With a 0.05 cap and a 1.0 ceiling, an AFFIRMATION needs ~20 bumps to saturate — probably fine but worth measuring against AFFIRMATION churn.
- **Q103.3.** The phase generates counterfactuals but doesn't surface them for operator inspection. Should they be on the review gate list? Deferred to spec 46 extension.
- **Q103.4.** Counterfactuals are subject to the non-durable prune that immediately follows. That's a TTL-style cleanup; short-lived counterfactuals may not survive long enough to match a later AFFIRMATION. May need a longer TTL for this kind specifically.
