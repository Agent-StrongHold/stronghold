# Spec 94 — Weekly self-dialogue ritual

*Once a week the self samples recent I_DID and I_WAS_TOLD memories about itself, runs a dialectic dialogue reconciling the two streams, and feeds the dialogue summary into the HEXACO retest plus one structured LESSON.*

**Depends on:** [personality.md](./personality.md), [self-reflection-ritual.md](./self-reflection-ritual.md), [memory-mirroring.md](./memory-mirroring.md), [litellm-provider.md](./litellm-provider.md), [self-schedules.md](./self-schedules.md).
**Depended on by:** (none yet — upstream consumers may reference the LESSON bucket structure).

---

## Current state

Personality (spec 23) runs a weekly 20-item HEXACO retest blended at 0.25. Self-reflection ritual exists but is isolated — it doesn't explicitly reconcile what the self *did* with what the self *was told about itself*. The two streams drift independently: the self's self-view (I_DID) and others' view (I_WAS_TOLD) never meet in a single write.

## Target

Weekly scheduled ritual (same cadence as the HEXACO retest). Samples `DIALOGUE_SAMPLE_I_DID = 15` recent I_DID memories and `DIALOGUE_SAMPLE_I_WAS_TOLD = 15` recent I_WAS_TOLD memories about the self. Runs a round-limited inward dialogue (capped at `DIALOGUE_ROUND_MAX = 6` rounds) producing a structured LESSON with three buckets — worked / failed / preference. The dialogue's summary becomes an input to that week's retest. If dialogue fails, retest falls back to the standard 20-item quiz. The dialogue LESSON mirrors via memory-mirroring.

## Acceptance criteria

### Cadence + scheduling

- **AC-94.1.** Scheduled via self-schedules.md at weekly cadence, same anchor day/time as the HEXACO retest. Test scheduler registers one entry per self.
- **AC-94.2.** Rate-limit: one dialogue per self per 7 days (enforced even if the scheduler misfires). Test duplicate firing is a no-op.
- **AC-94.3.** Missed run (job skipped more than 36h late) is dropped, not catch-up-run. Retest still proceeds next week. Test.

### Sampling

- **AC-94.4.** I_DID sample: most-recent `DIALOGUE_SAMPLE_I_DID = 15` memories with `source = I_DID` in the last 14 days. Test.
- **AC-94.5.** I_WAS_TOLD sample: most-recent `DIALOGUE_SAMPLE_I_WAS_TOLD = 15` memories with `source = I_WAS_TOLD` AND context.subject = self_id in the last 14 days. Test filter.
- **AC-94.6.** If either stream has fewer than 5 samples, dialogue is skipped for the week (insufficient reconciliation material) and retest falls back to standard quiz. Test both empty-stream cases.

### Dialogue execution

- **AC-94.7.** Dialogue is executed via litellm-provider with two roles: `self_voice` (persona anchored in current HEXACO + passions) and `other_voice` (composed from I_WAS_TOLD subjects). Test role binding.
- **AC-94.8.** Hard round cap: `DIALOGUE_ROUND_MAX = 6`. A round = one self_voice turn + one other_voice turn. Dialogue halts at cap even mid-exchange. Test cap enforced.
- **AC-94.9.** Dialogue timeout: `DIALOGUE_TIMEOUT_SEC = 120` wall-clock. Exceeding triggers the fallback path (AC-94.13). Test.

### LESSON output

- **AC-94.10.** Dialogue's summarizer produces a LESSON with exactly three buckets:
  ```
  {
      worked:     list[str],  # up to 5 items
      failed:     list[str],  # up to 5 items
      preference: list[str],  # up to 5 items
  }
  ```
  Empty buckets are allowed; total items capped at 15. Test schema validation.
- **AC-94.11.** LESSON is written with `source = I_DID`, tier = LESSON, and `context = {dialogue_id, i_did_sample_ids, i_was_told_sample_ids}`. Test provenance persists.
- **AC-94.12.** LESSON mirrors into episodic memory via memory-mirroring helpers (spec 32). Test mirror row exists.

### Retest input hook

- **AC-94.13.** The dialogue summary (not the full transcript) is injected as a `prior_context` field on the HEXACO retest prompt. Test the retest prompt includes the summary when dialogue succeeded.
- **AC-94.14.** If dialogue fails (timeout, insufficient samples, LLM error), the retest proceeds with the standard 20-item quiz and no `prior_context` field. Test both branches.
- **AC-94.15.** Retest blend weight remains 0.25 regardless of whether dialogue contributed. Test.

### Observability

- **AC-94.16.** Prometheus: `turing_self_dialogue_runs_total{self_id,outcome}` where outcome ∈ {success, insufficient_samples, timeout, error}. Counter `turing_self_dialogue_rounds{self_id}` histogram. Test.
- **AC-94.17.** Dialogue transcript (redacted per spec 40 if applicable) stored under `dialogues/{dialogue_id}.json` for operator audit; retained 90 days. Test.

## Implementation

```python
# rituals/self_dialogue.py

DIALOGUE_SAMPLE_I_DID: int = 15
DIALOGUE_SAMPLE_I_WAS_TOLD: int = 15
DIALOGUE_ROUND_MAX: int = 6
DIALOGUE_TIMEOUT_SEC: int = 120
DIALOGUE_MIN_STREAM_SAMPLES: int = 5


@dataclass(frozen=True)
class DialogueLesson:
    worked: list[str]
    failed: list[str]
    preference: list[str]


async def run_weekly(repo, llm, self_id: str, now: datetime) -> DialogueLesson | None:
    did = repo.recent_memories(self_id, source="I_DID", limit=DIALOGUE_SAMPLE_I_DID,
                               within=timedelta(days=14))
    told = repo.recent_memories(self_id, source="I_WAS_TOLD", about=self_id,
                                limit=DIALOGUE_SAMPLE_I_WAS_TOLD,
                                within=timedelta(days=14))
    if len(did) < DIALOGUE_MIN_STREAM_SAMPLES or len(told) < DIALOGUE_MIN_STREAM_SAMPLES:
        return None
    try:
        transcript = await asyncio.wait_for(
            _run_dialogue(llm, self_id, did, told, max_rounds=DIALOGUE_ROUND_MAX),
            timeout=DIALOGUE_TIMEOUT_SEC,
        )
    except (asyncio.TimeoutError, LlmError):
        return None
    lesson = _summarize(transcript)
    repo.write_lesson(self_id, lesson, context={
        "dialogue_id": transcript.id,
        "i_did_sample_ids": [m.id for m in did],
        "i_was_told_sample_ids": [m.id for m in told],
    })
    memory_mirroring.mirror_lesson(repo, self_id, lesson)
    return lesson
```

## Open questions

- **Q94.1.** Should `other_voice` draw from actual conversation partners' names or stay generic? Leaning generic until privacy review.
- **Q94.2.** Round cap of 6 — pulled from pilot experience. Too few for deep reconciliation? Measure bucket-fill rate and tune.
- **Q94.3.** Dialogue summary length budget for the retest prompt — currently unbounded. Add a hard cap (e.g. 1KB) once retest prompt-budget telemetry exists.
- **Q94.4.** Could REGRETs surface in the `failed` bucket explicitly? Yes — but avoid double-writing REGRETs. Keep the bucket as a digest, not a promotion path.
