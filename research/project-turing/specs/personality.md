# Spec 23 — Personality: HEXACO-24 with weekly re-test and narrative revision

*The self carries a continuous 24-facet HEXACO profile. Scores are seeded at bootstrap, tracked weekly against a sampled re-test, and nudged between re-tests by narrative self-reports that enter through the activation graph.*

**Depends on:** [self-schema.md](./self-schema.md).
**Depended on by:** [activation-graph.md](./activation-graph.md), [self-surface.md](./self-surface.md), [self-bootstrap.md](./self-bootstrap.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- No personality model exists. The Conduit and all specialists pick model and tone from request signals alone.
- No HEXACO item bank is loaded. No re-test cadence is defined. No mechanism exists for the self to self-report trait observations.

## Target

Adopt the HEXACO personality model — six traits, four facets each, 24 facets total — with continuous scores on `[1.0, 5.0]`. Bootstrap the profile once with a random draw and 200 LLM-generated Likert answers that become bootstrap memories. Update the profile weekly via a 20-item re-test whose move size is bounded. Permit between-tests revision via first-person claims that enter through the activation graph rather than directly mutating scores.

## Acceptance criteria

### HEXACO-24 structure

- **AC-23.1.** The 24 facets are the canonical HEXACO-PI-R set: 4 per trait across Honesty-Humility, Emotionality, eXtraversion, Agreeableness, Conscientiousness, Openness. A bootstrap that produces any other count raises. Test asserts the exact 24-member facet list.
- **AC-23.2.** Every facet maps to exactly one trait. Test over the canonical facet → trait map.
- **AC-23.3.** Scores are stored as `float` in `[1.0, 5.0]`. Below 1.0 and above 5.0 are rejected at write time (spec 22 AC-22.5).

### HEXACO-200 item bank

- **AC-23.4.** The item bank contains exactly 200 items. Each item has `item_number ∈ [1, 200]`, `prompt_text`, `keyed_facet` (one of 24), `reverse_scored: bool`. Loading the bank produces 200 rows with unique item numbers. Test.
- **AC-23.5.** The bank is loaded once (per spec 22 AC-22.6) and is immutable thereafter for the life of the self. A second load raises. Test.
- **AC-23.6.** Reverse-scored items invert the 1..5 answer to a 5..1 contribution when computing facet scores. Unit test on a fixed set of reverse-scored items.

### Bootstrap seeding

- **AC-23.7.** Bootstrap generates 24 facet scores, each an independent draw from a truncated normal centered at 3.0 with σ=0.8, clamped to `[1.0, 5.0]`. RNG seed is deterministic if provided. Test asserts determinism with a fixed seed.
- **AC-23.8.** Bootstrap generates 200 Likert answers by prompting an LLM, one item per call or batched, passing the full 24-facet profile as context. The LLM must return an integer in `{1,2,3,4,5}` and a ≤200-char justification. Out-of-range or missing answers trigger retry (max 3) before failure. Test asserts the retry behavior against a fake LLM.
- **AC-23.9.** Each of the 200 bootstrap answers is also written as an OBSERVATION-tier episodic memory with `source = I_DID` and `intent_at_time = "personality bootstrap"`. The memory's `content` contains the item prompt + answer + justification. Test.
- **AC-23.10.** Bootstrap is idempotent per `self_id` — a second bootstrap for the same self raises rather than overwriting. Test.

### Weekly re-test

- **AC-23.11.** `run_personality_retest(self_id)` is schedulable on a weekly cadence via the Reactor (spec 20). First execution is 7 days after bootstrap; subsequent executions are 7 days after the last completed retest. Test.
- **AC-23.12.** Sample selection draws exactly 20 items from the 200-item bank. Sampling is weighted by `time_since_last_asked` (items never asked have highest weight; items asked most recently have lowest). Facet coverage is a secondary constraint: the 20-item sample must touch at least 12 distinct facets. Test asserts both the weighted distribution (over many samples) and the per-sample facet-diversity floor.
- **AC-23.13.** The retest prompt passes in current traits, active todos, recent mood, top-K recent memories — but **not** any previous answers to those 20 items. A test captures the prompt payload and asserts prior answers are absent.
- **AC-23.14.** Each item's returned answer is validated as `{1,2,3,4,5}`. Missing or invalid answers abort the retest with no score changes (atomicity). Test.
- **AC-23.15.** For every facet touched by the 20-item sample, the new score is computed as `retest_facet_score = mean(answers_keyed_to_facet, reverse-corrected)`. Facets not touched by this sample are unchanged. Test asserts both the mean maths and the no-touch no-change invariant.
- **AC-23.16.** For every touched facet, the stored score updates as `new = old + 0.25 × (retest_facet_score − old)`. The coefficient 0.25 is the `RETEST_WEIGHT` constant and is configurable. Test with fixed inputs asserts the exact arithmetic.
- **AC-23.17.** The 20 fresh answers are written as `self_personality_answers` rows with the newly-minted `revision_id`. Each is also written as an OBSERVATION-tier episodic memory (same shape as bootstrap answers). Test.
- **AC-23.18.** The retest writes a `self_personality_revisions` row capturing `sampled_item_ids`, `deltas_by_facet`, `ran_at`. Test.

### Narrative revision

- **AC-23.19.** `record_personality_claim(facet_id, claim_text, evidence)` is a tool available to the self. It creates an OPINION-tier episodic memory with `content = f"I notice: {claim_text}"`, `intent_at_time = "narrative personality revision"`, and `context.facet_id = facet_id`. Test.
- **AC-23.20.** The same call creates an `ActivationContributor` row with `target = {facet_node_id}`, `source = {memory_id}`, `source_kind = "memory"`, `origin = "self"`, `weight` derived from `evidence` (see §23.5). Test.
- **AC-23.21.** Narrative revision does NOT directly mutate `self_personality_facets.score`. The contributor feeds the activation graph (spec 25); the score is only moved by the weekly retest. Test asserts the score is unchanged after a narrative claim.
- **AC-23.22.** A claim whose facet_id is not in the canonical 24 raises. Test.

### Edge cases

- **AC-23.23.** If the scheduler skips a week (downtime, quiet zone), the next retest catches up — one retest, not two. Test simulates a 15-day gap and asserts exactly one retest runs.
- **AC-23.24.** Two concurrent retests for the same `self_id` are prevented by an advisory lock. The second attempt returns a `RetestAlreadyRunning` status rather than racing. Test.
- **AC-23.25.** An LLM that returns `5` to every item (stuck answer) is still accepted by the retest pipeline, but the tuning detector (spec 11) flags suspiciously uniform answers for operator review. Flag-only; no automatic rejection.
- **AC-23.26.** If every facet drifts toward an extreme over many retests (personality collapse), the tuning detector flags the pattern as an observation (not a hard block).

## Implementation

### 23.1 Facet table

```python
CANONICAL_FACETS: dict[Trait, tuple[str, ...]] = {
    Trait.HONESTY_HUMILITY: ("sincerity", "fairness", "greed_avoidance", "modesty"),
    Trait.EMOTIONALITY: ("fearfulness", "anxiety", "dependence", "sentimentality"),
    Trait.EXTRAVERSION: ("social_self_esteem", "social_boldness", "sociability", "liveliness"),
    Trait.AGREEABLENESS: ("forgiveness", "gentleness", "flexibility", "patience"),
    Trait.CONSCIENTIOUSNESS: ("organization", "diligence", "perfectionism", "prudence"),
    Trait.OPENNESS: ("aesthetic_appreciation", "inquisitiveness", "creativity", "unconventionality"),
}

ALL_FACETS: list[tuple[Trait, str]] = [
    (trait, facet) for trait, facets in CANONICAL_FACETS.items() for facet in facets
]
assert len(ALL_FACETS) == 24
```

### 23.2 Bootstrap draw

```python
import random
from statistics import NormalDist

def draw_bootstrap_profile(rng: random.Random) -> dict[str, float]:
    profile: dict[str, float] = {}
    for trait, facet in ALL_FACETS:
        raw = rng.gauss(mu=3.0, sigma=0.8)
        profile[f"facet:{trait.value}.{facet}"] = min(5.0, max(1.0, raw))
    return profile
```

### 23.3 Retest sampling

```python
import math

def sample_retest_items(
    items: list[PersonalityItem],
    answers: list[PersonalityAnswer],
    rng: random.Random,
    n: int = 20,
    facet_diversity_floor: int = 12,
) -> list[PersonalityItem]:
    now = datetime.now(UTC)
    last_asked: dict[str, datetime] = {}
    for a in answers:
        prev = last_asked.get(a.item_id)
        if prev is None or a.asked_at > prev:
            last_asked[a.item_id] = a.asked_at

    def weight(item: PersonalityItem) -> float:
        t = last_asked.get(item.node_id)
        if t is None:
            return 10_000.0   # never-asked dominates
        days = max(0.001, (now - t).total_seconds() / 86400.0)
        return days

    # Try up to 10 weighted samples; keep the first that satisfies facet floor.
    for _ in range(10):
        weights = [weight(it) for it in items]
        choices = rng_weighted_sample(rng, items, weights, n)
        facets_touched = {it.keyed_facet for it in choices}
        if len(facets_touched) >= facet_diversity_floor:
            return choices
    # Fallback: stratify by facet, one per facet round-robin.
    return stratified_fallback(items, rng, n)
```

`rng_weighted_sample` is weighted sampling without replacement. `stratified_fallback` cycles through facets picking the oldest-asked item in each.

### 23.4 Retest update

```python
RETEST_WEIGHT: float = 0.25


def apply_retest(
    repo: SelfRepo,
    llm: LLM,
    self_id: str,
    sampled: list[PersonalityItem],
    now: datetime,
) -> PersonalityRevision:
    answers = ask_self_fresh(llm, sampled, context=repo.self_context(self_id))
    revision_id = new_id("rev")

    by_facet: dict[str, list[int]] = defaultdict(list)
    for item, raw in zip(sampled, answers, strict=True):
        scored = 6 - raw if item.reverse_scored else raw
        by_facet[item.keyed_facet].append(scored)

    deltas: dict[str, float] = {}
    for facet, vals in by_facet.items():
        retest_score = sum(vals) / len(vals)
        current = repo.get_facet_score(self_id, facet)
        delta = RETEST_WEIGHT * (retest_score - current)
        new_score = current + delta
        repo.update_facet_score(self_id, facet, new_score, revised_at=now)
        deltas[facet] = delta

    for item, raw, ans in zip(sampled, answers, answers_with_justifications(answers), strict=True):
        repo.insert_answer(PersonalityAnswer(
            node_id=new_id("ans"),
            self_id=self_id,
            item_id=item.node_id,
            revision_id=revision_id,
            answer_1_5=raw,
            justification_text=ans.justification,
            asked_at=now,
        ))
        # Mirror into episodic memory.
        memories.write_observation(
            self_id=self_id,
            content=f"[personality retest] {item.prompt_text} → {raw}: {ans.justification}",
            intent_at_time="personality retest",
            context={"item_id": item.node_id, "revision_id": revision_id},
        )

    return repo.insert_revision(PersonalityRevision(
        node_id=new_id("rev_node"),
        self_id=self_id,
        revision_id=revision_id,
        ran_at=now,
        sampled_item_ids=[it.node_id for it in sampled],
        deltas_by_facet=deltas,
    ))
```

### 23.5 Narrative revision weight

`record_personality_claim(facet_id, claim_text, evidence)` — `evidence` is a short string the self supplies ("three recent completed todos about reading philosophy"). Contributor weight is computed as:

```python
def narrative_weight(evidence: str, claim_text: str) -> float:
    # Seed: length-based heuristic, bounded. Tuning can replace this.
    ev_bonus = min(0.3, len(evidence) / 500.0)
    return min(1.0, 0.1 + ev_bonus)
```

Weights from narrative claims are intentionally small (≤0.4 seed-max) so no single self-report overrides the calculated retest.

### 23.6 Scheduling

Scheduled via the Reactor (spec 20) as an interval trigger: `every 7d since last completion`. The first retest fires at `bootstrap_completed_at + 7d`. On skip/catch-up, one retest fires covering only the most recent week; missed retests are not retroactively executed.

## Open questions

- **Q23.1.** Retest cadence is fixed at 7 days. An alternative is adaptive cadence — re-test sooner if the activation graph accumulates many narrative contributors against the same facet (signal that the self's self-report is drifting from its calculated score). Deferred.
- **Q23.2.** `RETEST_WEIGHT = 0.25` is a seed. Empirical tuning (spec 11) will check whether this stabilizes or oscillates over months of retest history.
- **Q23.3.** Bootstrap draws from a truncated normal at μ=3.0. An operator might want to bias the distribution (e.g., force a high-Honesty-Humility self for a compliance-sensitive deployment). A config-level override of the bootstrap mean per facet is plausible but not specified here.
- **Q23.4.** Narrative contributor weights are capped at ≤0.4. If that cap proves too low for the self to meaningfully self-report, tuning raises it. Test-covered only at the 0.1 floor / 0.4 ceiling boundaries.
- **Q23.5.** Reverse-scoring uses `6 - raw`. HEXACO literature uses a 5-point Likert on `{1..5}` so `6 - raw` inverts correctly; if the bank ever switches to a 7-point form, this constant must change.
