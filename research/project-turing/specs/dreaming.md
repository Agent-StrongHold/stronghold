# Spec 12 — Dreaming: scheduled consolidation, WISDOM write path

*Scheduled, phase-gated process that walks durable memories, extracts patterns, and produces WISDOM candidates through a review gate. Undeferred from [wisdom-write-path.md](./wisdom-write-path.md) — dreaming is now the sole legitimate write path into the WISDOM tier.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md), [write-paths.md](./write-paths.md), [motivation.md](./motivation.md), [scheduler.md](./scheduler.md).
**Supersedes status of:** [wisdom-write-path.md](./wisdom-write-path.md) (tier is no longer reserved-but-unwritable; the constraints listed there become invariants the dreaming implementation must satisfy).

---

## Current state

After runtime chunks 1–5, the system accumulates REGRETs, ACCOMPLISHMENTs, AFFIRMATIONs, and LESSONs. It imagines and daydreams. It tunes its own coefficients. But it does not integrate what it has experienced into identity. WISDOM is structurally the tier for that integration and stays empty.

## Target

A **Dreamer** component, scheduled on a cron-style cadence (default 3 AM local), runs a bounded consolidation pass that walks durable memory, identifies patterns that warrant cross-context identity claims, and produces pending WISDOM candidates. Each candidate passes through a review gate before committing to the durable store. Any `tier = WISDOM` memory written must carry a traceable dreaming origin.

## Acceptance criteria

### Scheduling

- **AC-12.1.** Dreamer registers with the scheduler to run at `DREAM_SCHEDULE` (default `0 3 * * *`, 3 AM local time). Test asserts the next-fire calculation from a fixed clock.
- **AC-12.2.** A session is skipped if fewer than `DREAM_MIN_NEW_DURABLE` (default 5) durable memories have been added since the last session. Test asserts no session marker is written on a skip.
- **AC-12.3.** Only one session runs at a time. A second invocation while one is in-flight is ignored (logged). Test asserts concurrent-invocation behavior.
- **AC-12.4.** A session exceeding `DREAM_MAX_DURATION` (default 30 min) is truncated cleanly: phases not yet started are skipped, already-committed candidates remain, a partial-session marker is written. Test asserts truncation behavior.

### Phases

A session runs the following phases in order. Each has its own budget. Any phase may return zero work without failing the session.

- **AC-12.5. Phase 1 (pattern extraction).** Walks REGRETs and ACCOMPLISHMENTs added since the last session. Clusters them by `intent_at_time` family and outcome polarity. Emits zero or more pattern candidates with supporting `memory_id` lists. Test asserts clusters form over a seeded fixture.
- **AC-12.6. Phase 2 (WISDOM candidacy).** For each pattern with `≥ WISDOM_N` (default 5) supporting memories, a *pending* WISDOM candidate is minted in a staging store. Pending candidates are not visible to retrieval. Test asserts pending-staging separation.
- **AC-12.7. Phase 3 (AFFIRMATION proposal).** For patterns whose invariant suggests forward commitment (not just retrospective claim), an AFFIRMATION proposal is queued. These follow the existing [write-paths.md AFFIRMATION](./write-paths.md) path. Test asserts commit.
- **AC-12.8. Phase 4 (LESSON consolidation).** Pairs of contradictory stance memories whose resolution is known collapse into a LESSON with `supersedes_via_lineage` covering both. (Duplicates the [contradiction detector](./detectors/contradiction.md) but runs cross-intent, slower, and with bigger windows.) Test asserts LESSON minting.
- **AC-12.9. Phase 5 (non-durable pruning).** OBSERVATIONs and HYPOTHESISes whose weight has stayed below `MIN_RETAIN_WEIGHT` (default 0.15) for `DREAM_PRUNE_HORIZON` (default 30 days) are soft-deleted. Durable tiers are never touched in this phase. Test asserts non-durable-only.
- **AC-12.10. Phase 6 (review gate).** Pending WISDOM candidates pass a self-consistency check: a candidate contradicting existing WISDOM is rejected (not silently superseding); a candidate whose supporting lineage contains at least one superseded memory is rejected. Test asserts both rejections and one pass-through. In a future `main` port, the gate becomes operator-reviewed.
- **AC-12.11. Phase 7 (session marker).** Exactly one `tier = OBSERVATION`, `source = I_DID` memory is written per session, recording: start/end timestamps, per-phase counts, committed candidate IDs, rejected candidate IDs. Test asserts the marker schema.

### WISDOM write invariants (enforced repository-side)

- **AC-12.12.** Any `durable_memory` INSERT with `tier = wisdom` must have `origin_episode_id IS NOT NULL`. Enforced at the schema/repo layer. Test asserts rejection when missing.
- **AC-12.13.** The `origin_episode_id` must point at an OBSERVATION session marker whose content starts with `dream session `. Enforced at the repo layer (foreign-key-equivalent via query). Test asserts rejection when dangling.
- **AC-12.14.** The `context` JSON must contain `supersedes_via_lineage` as a non-empty list of memory_ids referencing real durable memories in `{regret, accomplishment, lesson, affirmation}`. Test asserts rejection when missing or referencing non-existent memories.
- **AC-12.15.** A committed WISDOM candidate cannot supersede existing WISDOM. It can only extend. Attempt to set `supersedes` pointing at a WISDOM memory_id is rejected. Test asserts.
- **AC-12.16.** Per-session candidate cap: `DREAM_MAX_WISDOM_CANDIDATES` (default 3) enforced by the Dreamer (not the repo). Exceeding the cap drops the excess candidates. Test asserts cap.

### Failure semantics

- **AC-12.17.** A crash / OOM / timeout during a session leaves already-committed candidates in place (they are `immutable=True`) and writes a partial-session marker recording phase progress. Test asserts recovery via induced failure.
- **AC-12.18.** A rejected candidate is recorded in the session marker but not elsewhere. Test asserts no ghost rows in durable_memory.

## Implementation

### 12.1 Dreamer shape

```python
class Dreamer:
    def __init__(
        self,
        *,
        reactor,
        motivation,
        repo,
        scheduler,
        self_id: str,
        schedule_cron: str = "0 3 * * *",
        min_new_durable: int = 5,
        wisdom_n: int = 5,
        max_candidates: int = 3,
        max_duration: timedelta = timedelta(minutes=30),
        min_retain_weight: float = 0.15,
        prune_horizon: timedelta = timedelta(days=30),
    ) -> None: ...

    # Scheduled: scheduler fires this at schedule_cron
    def run_session(self) -> DreamSessionReport: ...

    # Phases as private methods:
    def _phase1_extract_patterns(...) -> list[Pattern]: ...
    def _phase2_mint_wisdom_candidates(...) -> list[PendingCandidate]: ...
    def _phase3_propose_affirmations(...) -> None: ...
    def _phase4_consolidate_lessons(...) -> None: ...
    def _phase5_prune_non_durable(...) -> None: ...
    def _phase6_review_gate(...) -> tuple[list[PendingCandidate], list[Rejection]]: ...
    def _phase7_write_session_marker(...) -> None: ...
```

### 12.2 Staging for pending candidates

Pending WISDOM candidates live in a separate in-memory (or short-TTL) store until the review gate fires. They are *not* inserted into `durable_memory` until phase 6 approves. This preserves INV-6 (append-only) — no ghost rows from rejected candidates.

### 12.3 Pattern extraction (phase 1)

Cluster durable memories by `intent_at_time` family; compute per-cluster:

- count of REGRETs and ACCOMPLISHMENTs
- ratio of positive to negative outcomes
- mean confidence_at_creation and surprise_delta
- time span

A cluster qualifies as a pattern if count ≥ `WISDOM_N` and the outcome ratio is directionally consistent (> 80% one polarity, or > 80% LESSONs pointing the same direction).

### 12.4 Review gate (phase 6)

Rejects when:

- Candidate content semantically contradicts an existing non-superseded WISDOM entry. (Semantic check: simple string-shape for the research sketch, LLM-backed for production.)
- Any memory in `supersedes_via_lineage` has `superseded_by is not None`.
- Candidate attempts to supersede existing WISDOM (see AC-12.15).

Pass-through writes the candidate to `durable_memory` with `immutable=True`, `source=I_DID`, `origin_episode_id=<session_marker_id>`, `context.supersedes_via_lineage=<list>`.

### 12.5 Session marker

Written at phase 7 *before* committing WISDOM candidates (so the marker exists for `origin_episode_id` references). A placeholder marker's memory_id is minted first; committed candidates reference it; the marker's content is updated at session end with counts.

*Implementation note:* Because durable memories are append-only and most fields are frozen (INV-6), "updating" the marker at session end means writing a *second* OBSERVATION with `supersedes` pointing at the placeholder. The `origin_episode_id` on WISDOM entries still resolves to the placeholder; operators querying session history walk forward to the final marker via `superseded_by`.

## Configuration constants

```python
DREAM_SCHEDULE:              str        = "0 3 * * *"
DREAM_MIN_NEW_DURABLE:       int        = 5
DREAM_WISDOM_N:              int        = 5
DREAM_MAX_WISDOM_CANDIDATES: int        = 3
DREAM_MAX_DURATION:          timedelta  = timedelta(minutes=30)
DREAM_MIN_RETAIN_WEIGHT:     float      = 0.15
DREAM_PRUNE_HORIZON:         timedelta  = timedelta(days=30)
```

All runtime-tunable via the CoefficientTuner's AFFIRMATION path.

## Open questions

- **Q12.1.** Cron-style scheduling in the Reactor: main's Reactor supports TIME triggers at HH:MM; the research-branch `RealReactor` doesn't have native cron. Simplest port: a handler that polls `datetime.now()` each tick and runs when the crossing happens. More robust: a `SchedulerEntry` in `scheduler.py` accepting cron expressions.
- **Q12.2.** Semantic "contradicts existing WISDOM" check in phase 6 is handwaved. For the initial sketch, string-shape patterns from [contradiction.md](./detectors/contradiction.md) are reused. Production requires an LLM-backed contradiction check, which re-adds the exact dependency WISDOM's deferral was supposed to avoid. Revisit.
- **Q12.3.** Pattern extraction (phase 1) uses simple cluster counts. Higher-quality extraction would use embeddings. Deferred; today's approach is the cheapest that produces an identifiable pattern.
- **Q12.4.** If a session's phase 4 (LESSON consolidation) overlaps with the live contradiction detector's work, both produce LESSONs for the same triple. Dedup is by `dedup_key` in the detector; dreaming phase 4 should consult the same dedup index or risk duplicate LESSONs. Implementation detail worth calling out.
- **Q12.5.** The "review gate" is automatic in research mode; per spec §6 it's operator-reviewed in any main port. The structural shape is the same (a pending staging store gating commits); the difference is who approves. This spec doesn't try to design the operator UX.
