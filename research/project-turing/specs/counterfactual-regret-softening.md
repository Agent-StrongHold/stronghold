# Spec 109 — Counterfactual REGRET softening

*REGRETs cannot decay below the 0.6 weight floor — that is the identity-anchor invariant. But when the underlying cause is demonstrably resolved, dreaming mints an `I-have-grown-past-this` annotation that lowers the REGRET's retrieval salience without touching its weight. The REGRET stays as anchor; it stops dominating recall.*

**Depends on:** [retrieval.md](./retrieval.md), [bitemporal-perspective-replay.md](./bitemporal-perspective-replay.md), [dreaming.md](./dreaming.md), [durability-invariants.md](./durability-invariants.md), [learning-extraction-detector.md](./learning-extraction-detector.md).

---

## Current state

REGRET memories have a weight floor of 0.6 (durability-invariants spec). They cannot be soft-deleted and they resist decay. This is correct — REGRETs are supposed to anchor "never again" identity commitments. But a consequence is that a REGRET from 2025 about a long-resolved failure pattern keeps dominating retrieval into 2026, crowding out newer ACCOMPLISHMENTs that replace the pattern. There is no current mechanism to say "this REGRET is still true, still retained, but no longer top-of-mind."

## Target

A dreaming-phase pass that, for each REGRET, evaluates whether the underlying cause has been superseded by evidence:

1. `N` successful counter-trajectories on the same request-shape over 30 days (via learning-extraction similarity machinery, spec 63).
2. At least one AFFIRMATION on the same request-shape.
3. No contradicting REGRET within the 30-day window.

When all three hold, mint a `salience_modifier = 0.5` annotation that halves the REGRET's retrieval weight, leaving `weight` and `weight_floor` untouched. The annotation is itself an I_DID OBSERVATION linked to the REGRET. Recurrence of the cause revokes the annotation.

## Acceptance criteria

### Schema additions

- **AC-109.1.** A new `salience_modifier REAL NOT NULL DEFAULT 1.0` column on the memory table. Migration backfills existing rows with 1.0. Test the migration is idempotent.
- **AC-109.2.** Retrieval-weight formula updated: `effective_retrieval_weight = weight × salience_modifier`. REGRET-specific queries (`WHERE tier = 'regret'`) ignore `salience_modifier` — they still surface softened REGRETs for audit/digest. Test.

### Eligibility

- **AC-109.3.** Default N = 10 successful counter-trajectories with request-embedding similarity ≥ 0.75 to the REGRET's request-shape, within 30 days. Configurable via `TURING_REGRET_SOFTEN_N` and `TURING_REGRET_SOFTEN_WINDOW_DAYS`. Test boundaries.
- **AC-109.4.** Required: ≥1 AFFIRMATION memory whose request-embedding similarity to the REGRET is ≥ 0.75 within the same 30-day window. Test skipped when missing.
- **AC-109.5.** Disqualifier: any REGRET minted within the window whose request-embedding similarity is ≥ 0.75. Test a newer similar REGRET blocks softening.

### Annotation semantics

- **AC-109.6.** Softening sets `salience_modifier = 0.5`. `weight` and `weight_floor` are unchanged (invariant-preserving). Test both fields unchanged.
- **AC-109.7.** Softening mints an I_DID OBSERVATION `"I have grown past the pattern behind REGRET {id}: {N} successes, AFFIRMATION on same shape, no recurrence in {window} days."` The OBSERVATION's `context.softens_regret_id` = the REGRET id. Test.
- **AC-109.8.** A REGRET cannot be softened twice while the annotation is live. Re-running the pass on an already-softened REGRET is a no-op. Test.

### Reversal

- **AC-109.9.** If a new REGRET is minted with request-embedding similarity ≥ 0.8 to a softened REGRET, the softening is revoked: `salience_modifier` resets to 1.0 and a second I_DID OBSERVATION is minted `"The cause has recurred; I have not grown past this."` linking both REGRETs. Test.
- **AC-109.10.** Revocation is idempotent — if `salience_modifier` is already 1.0, the revocation still mints the recurrence OBSERVATION (the identity signal matters) but does not double-reset. Test.

### Forensics & observability

- **AC-109.11.** Softening events and revocations are `forensic_tag = "regret_softening"`. Test bulk retraction removes all modifiers and related OBSERVATIONs.
- **AC-109.12.** Prometheus counters `turing_regret_softened_total{self_id}` and `turing_regret_softening_revoked_total{self_id}`. Test.
- **AC-109.13.** `stronghold self digest` surfaces softened REGRETs distinctly from active REGRETs. Test.

### Edge cases

- **AC-109.14.** A REGRET with no request-embedding (embedding failure) is never eligible for softening. Test.
- **AC-109.15.** The pass runs during dreaming phase 4 and respects `MAX_SOFTENINGS_PER_DREAM = 10` to avoid large batch effects. Test cap.
- **AC-109.16.** Softening respects bitemporal-perspective-replay (spec 90): replaying from a perspective before the softening event sees `salience_modifier = 1.0` at that transaction time. Test via `tt_as_of`.

## Implementation

```python
# dreaming/phases/regret_softening.py

SOFTEN_N: int = 10
SOFTEN_WINDOW: timedelta = timedelta(days=30)
SIMILARITY_MIN: float = 0.75
RECURRENCE_MIN: float = 0.80
MAX_PER_DREAM: int = 10
SOFT_MOD: float = 0.5


def run(repo, self_id: str, now: datetime) -> tuple[int, int]:
    softened = revoked = 0
    # First pass: revocations (always check, even when cap is full)
    for softened_regret in repo.softened_regrets(self_id):
        recent_similar = repo.recent_similar_regrets(
            self_id, softened_regret.id, since=now - SOFTEN_WINDOW, min_sim=RECURRENCE_MIN,
        )
        if recent_similar:
            repo.revoke_softening(softened_regret.id, recent_similar[0].id, now)
            revoked += 1
    # Second pass: new softenings
    for regret in repo.unsoftened_regrets(self_id):
        if softened >= MAX_PER_DREAM:
            break
        if not regret.request_embedding:
            continue
        successes = repo.count_similar_successes(
            self_id, regret.request_embedding, min_sim=SIMILARITY_MIN,
            since=now - SOFTEN_WINDOW,
        )
        if successes < SOFTEN_N:
            continue
        if not repo.has_similar_affirmation(self_id, regret.request_embedding, SIMILARITY_MIN, now - SOFTEN_WINDOW):
            continue
        if repo.has_contradicting_regret(self_id, regret.id, SIMILARITY_MIN, now - SOFTEN_WINDOW):
            continue
        repo.apply_softening(regret.id, SOFT_MOD, now, context={"successes": successes})
        softened += 1
    return softened, revoked
```

## Open questions

- **Q109.1.** `salience_modifier = 0.5` is a heuristic halving. A graduated curve (0.8 at N=10, 0.5 at N=30, floor at 0.3) is plausible but adds tuning surface. Start with a step function; revisit.
- **Q109.2.** We check AFFIRMATION presence on the same request-shape but not its *recency*. A 29-day-old AFFIRMATION followed by 28 days of silence is still treated as valid evidence. Probably fine; borderline.
- **Q109.3.** Request-embedding similarity thresholds (0.75 for success, 0.80 for recurrence) are asymmetric on purpose — softening is generous, revocation is strict. The invariant we care about is "never miss a real recurrence." Borderline cases resolve as "unsoftened," which is safe.
- **Q109.4.** Should softening ever affect dream-selection weighting? Today it only affects retrieval. We could also dampen dream surfacing. Deferred — dreaming is how the self *works through* residual regrets, so we likely want the unmodified weight there.
