# Spec 59 — Source identity and emergent reliability

*Per-source identity (named providers) layered on top of the existing `SourceKind` perspective enum. Reliability is a per-source scalar emergent from regret history; it feeds retrieval ranking, the contradiction-detection threshold, and a regret-on-regret LESSON path when a source crosses a sustained-unreliability floor.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [write-paths.md](./write-paths.md), [persistence.md](./persistence.md), [tool-layer.md](./tool-layer.md), [bi-temporal-validity.md](./bi-temporal-validity.md).
**Depended on by:** [as-of-retrieval.md](./as-of-retrieval.md) (ranking-aware retrieval), [regret-severity-and-load-bearing.md](./regret-severity-and-load-bearing.md) (citation chains include source-identity).

---

## Current state

`SourceKind` (spec 1) is a 3-value enum: `I_DID`, `I_WAS_TOLD`, `I_IMAGINED`. It captures the *perspective* of the act — "I did this" vs. "I was told this" — which is correct for an autonoetic Conduit, but flattens the *source actor*. A fact told by the user, a fact scraped from an RSS feed, and a fact returned by a tool call collapse to a single `I_WAS_TOLD`.

The corpus has no model of *which* external source a told-fact came from, and no notion that some sources turn out to be more reliable than others as the Conduit accumulates regret history.

## Target

A new table `source_identity` with one row per discovered external source. Each told-fact memory carries an optional `source_identity_id` referring to a row. Reliability is a column on the source row, computed from the regret history: facts from this source that were superseded into a REGRET pull reliability down; long-held unsuperseded facts pull it up.

`SourceKind` is unchanged — perspective is orthogonal to identity. A fact still carries `source = I_WAS_TOLD`; the new field qualifies *who told*.

### Reliability formula

Sigmoid of an exponentially-decayed signed score:

```
score(s, t) = Σ_{m ∈ facts_from(s)} contribution(m, t)
contribution(m, t) = sign(m, t) × exp(-(t - anchor(m, t)) / τ)
sign(m, t)         = -1 if m was superseded into a REGRET by time t
                   = +1 otherwise
anchor(m, t)       = supersession.event_at if superseded by t, else m.created_at
reliability(s, t)  = sigmoid(score(s, t) / SCALE)
```

Defaults: `τ = 90 days`, `SCALE = 5.0`. New sources start at `score = 0` → `reliability = 0.5`.

Unsuperseded facts contribute `+1` weighted by recency; the further past, the smaller the contribution. A burst of recent regrets pulls reliability down sharply; sustained absence-of-regret rebuilds it as the regret events decay.

### Feedback loops

1. **Retrieval ranking** (extension to spec 16). Rank score multiplier: `0.5 + 0.5 × reliability(source(m))`. A 0.0-reliability source ranks at 0.5×; 1.0 ranks at 1.0×.
2. **Contradiction threshold** (extension to spec 4 and `detectors/contradiction.md`). When a new fact contradicts an existing one, the threshold to mint a REGRET on the existing fact scales by `reliability(existing.source) / max(0.05, reliability(new.source))`. A new fact from an unreliable source must be more strongly confirmed to override an existing fact from a reliable source.
3. **Regret-on-regret LESSON** (new write path). When `reliability(s)` stays below `RELIABILITY_LESSON_FLOOR` (default 0.3) across `LESSON_TRIGGER_WINDOWS` (default 7) consecutive sample windows, mint exactly one LESSON: "Source `s.name` is unreliable; weight downstream facts accordingly." The LESSON's `context.derived_from_regrets` lists the regret memory_ids that pulled reliability down. Subsequent triggers within `LESSON_COOLDOWN_DAYS` (default 90) are suppressed.

## Acceptance criteria

### Schema

- **AC-59.1.** `source_identity` table created: `source_id (PK TEXT)`, `kind TEXT`, `name TEXT`, `created_at TIMESTAMP`, `last_updated_at TIMESTAMP`, `reliability REAL DEFAULT 0.5`, `last_lesson_at TIMESTAMP`. Unique on `(kind, name)`. Test schema and unique constraint.
- **AC-59.2.** `SourceProviderKind` enum: `USER, RSS_FEED, TOOL_CALL, AGENT, EXTERNAL_API, INTERNAL`. Test membership.
- **AC-59.3.** `EpisodicMemory` and `durable_memory` gain optional `source_identity_id TEXT`. Existing rows backfill with `NULL`. Test migration UP/DOWN.

### Identity resolution

- **AC-59.4.** `resolve_source(kind, name, repo) -> str` returns the `source_id` of an existing row matching `(kind, name)` or inserts a new row and returns its id. Test new-source path and reuse path; concurrent invocations must not produce duplicate rows.
- **AC-59.5.** Ingestion paths populate `source_identity_id`: user message ingestion (kind=USER, name=user_id), RSS reader ingestion (kind=RSS_FEED, name=feed_url), tool call results (kind=TOOL_CALL, name=tool_name), upstream-agent message handoff (kind=AGENT, name=agent_id). Self-introspection writes (kind=INTERNAL, name="conduit") are populated for `source = I_DID` memories that did not have a tool call. Test each shape.
- **AC-59.6.** `source_identity_id = NULL` is permitted for legacy / pre-migration rows. Reliability lookup on a `NULL` source returns the default `0.5` and emits a warning counter; ranking and contradiction-threshold use the default.

### Reliability computation

- **AC-59.7.** `compute_reliability(source_id, repo, t=now) -> float` returns a value in `[0, 1]`. New source returns `0.5`. Deterministic given the regret history and `t`. Property test over random regret sequences.
- **AC-59.8.** Decay correctness: a single REGRET older than `5τ` contributes `< 0.01` (absolute) to `score`. Test.
- **AC-59.9.** Recompute is incremental: a fact event triggers a single source's recompute, not a full sweep. Benchmark asserts recompute is `O(facts_from_source)`. Test with a 1000-source / 10000-fact fixture.
- **AC-59.10.** Stored `reliability` column is updated on every fact event from that source (insert, supersede). Reads use the stored value to avoid recompute on retrieval; recompute runs at write time. Test the write/read split.

### Retrieval ranking

- **AC-59.11.** A/B test: same query, two facts with identical similarity and tier weight, source reliabilities `0.2` and `0.8`. The `0.8` ranks first; the gap matches `(0.5 + 0.5×0.8) / (0.5 + 0.5×0.2) = 1.5×`. Test.
- **AC-59.12.** Ranking multiplier applies in both `now()` retrieval (spec 16) and `as_of(t)` retrieval (spec 58). The `as_of` path uses `compute_reliability(source_id, repo, t)`, not `reliability_at_now`. Test the as-of path with a regret that occurs after `t`; reliability at `t` is unaffected.

### Contradiction threshold

- **AC-59.13.** A spec-4 contradiction trigger that would mint REGRET at default thresholds does *not* mint when the new fact's source has `reliability = 0.2` and the existing fact's source has `reliability = 0.9`, unless `surprise_delta` exceeds the scaled threshold. Parametrized test.
- **AC-59.14.** Threshold scaling is bounded: `max(0.05, reliability)` in the denominator prevents division-by-zero and caps the maximum scale factor at `20×`. Test.

### Regret-on-regret LESSON

- **AC-59.15.** The reliability sampler runs once per UTC day (registered as a reactor interval trigger; spec 33 pattern). For each source, it records `(source_id, sampled_at, reliability)` in a rolling 30-day window. Test the trigger registration.
- **AC-59.16.** When a source has `LESSON_TRIGGER_WINDOWS` (default 7) consecutive sample windows with `reliability < RELIABILITY_LESSON_FLOOR` (default 0.3), the next sampler run mints exactly one LESSON. Subsequent triggers within `LESSON_COOLDOWN_DAYS` (default 90) are no-ops. Test the trigger / cooldown / re-trigger sequence.
- **AC-59.17.** The minted LESSON has `tier = LESSON`, `source = I_DID`, `source_identity_id = INTERNAL`, `content` LLM-drafted from the regret lineage (cleanroom prompt; warden-on-self-writes spec 36 applies), `context.derived_from_regrets = [regret_memory_id, ...]`, `context.about_source_id = source_id`. Test schema.
- **AC-59.18.** The minted LESSON does *not* itself drop the source's reliability (the LESSON is a derivation, not a new told-fact). Reliability is recomputed without the LESSON in the contribution sum. Test.
- **AC-59.19.** `INTERNAL` sources start at `reliability = 0.95`. Decay applies normally; no hard-coded immunity. A demonstrably unreliable internal path can therefore mint a LESSON about itself — expected. Test.

## Implementation

```python
# source_identity.py

class SourceProviderKind(StrEnum):
    USER = "user"
    RSS_FEED = "rss_feed"
    TOOL_CALL = "tool_call"
    AGENT = "agent"
    EXTERNAL_API = "external_api"
    INTERNAL = "internal"


@dataclass
class SourceIdentity:
    source_id: str
    kind: SourceProviderKind
    name: str
    created_at: datetime
    last_updated_at: datetime
    reliability: float
    last_lesson_at: datetime | None
```

```python
# reliability.py

TAU_DAYS = 90.0
SCALE = 5.0
RELIABILITY_LESSON_FLOOR = 0.3
LESSON_TRIGGER_WINDOWS = 7
LESSON_COOLDOWN_DAYS = 90
INTERNAL_SOURCE_PRIOR = 0.95


def compute_reliability(source_id: str, repo: SourceRepo, t: datetime | None = None) -> float:
    t = t or datetime.now(UTC)
    src = repo.get_source(source_id)
    if src.kind == SourceProviderKind.INTERNAL and not repo.facts_from(source_id):
        return INTERNAL_SOURCE_PRIOR
    score = 0.0
    for mem in repo.facts_from(source_id):
        anchor = repo.supersession_event_at(mem) or mem.created_at
        decay = exp(-((t - anchor).days) / TAU_DAYS)
        sign = -1.0 if repo.was_superseded_into_regret(mem, by=t) else +1.0
        score += sign * decay
    return _sigmoid(score / SCALE)
```

Retrieval-ranking hook (spec 16 augmentation):

```python
def _rank(candidates, query, repo):
    for c in candidates:
        r = repo.reliability_of(c.source_identity_id) if c.source_identity_id else 0.5
        c.rank_score = c.similarity * c.weight * (0.5 + 0.5 * r)
    return sorted(candidates, key=lambda c: -c.rank_score)
```

Contradiction threshold (spec 4 / `detectors/contradiction.md` extension):

```python
def contradiction_threshold(
    base: float, new_source_id: str | None, existing_source_id: str | None, repo: SourceRepo,
) -> float:
    r_new = repo.reliability_of(new_source_id) if new_source_id else 0.5
    r_old = repo.reliability_of(existing_source_id) if existing_source_id else 0.5
    return base * (r_old / max(0.05, r_new))
```

Regret-on-regret detector — reactor interval trigger (spec 33 pattern):

```python
def tick_reliability_sampler(state) -> None:
    today = datetime.now(UTC).date()
    for src in state.source_repo.all():
        r = compute_reliability(src.source_id, state.source_repo)
        state.source_repo.upsert_sample(src.source_id, today, r)
        recent = state.source_repo.recent_samples(src.source_id, days=LESSON_TRIGGER_WINDOWS)
        if (
            len(recent) >= LESSON_TRIGGER_WINDOWS
            and all(s.reliability < RELIABILITY_LESSON_FLOOR for s in recent)
            and (
                src.last_lesson_at is None
                or (datetime.now(UTC) - src.last_lesson_at).days >= LESSON_COOLDOWN_DAYS
            )
        ):
            mint_unreliable_source_lesson(state, src)
```

## Open questions

- **Q59.1.** Per-(source, predicate) reliability is more accurate — a source can be reliable about its domain and unreliable elsewhere — but is significantly more state. The simple per-source scalar covers the common case. Defer per-predicate reliability to a future spec; revisit when the property test reveals false-suppression of reliable-on-topic sources.
- **Q59.2.** `USER` source granularity: one source per user, or per `(user, topic-cluster)`? Current spec says per-user. Topic clustering is a downstream concern — see Q59.1.
- **Q59.3.** The regret-on-regret LESSON's content is LLM-drafted from the regret lineage. The cleanroom prompt is a separate artifact under spec 36. The LESSON tier is mintable only via this path and through the dreaming consolidation (spec 12); operator-issued "this source is unreliable" goes through standard write-paths.
- **Q59.4.** `INTERNAL` reliability prior of `0.95` is calibration-sensitive. The risk is that the Conduit overweights its own past introspection. The Tranche 9 guardrails (spec 39) and the regret-on-regret path are the safety net; revisit calibration if a guardrail audit shows internal-source overconfidence.
- **Q59.5.** Graph-walk over regret-citation chains by source (e.g., "for source X, find all cascading regrets that share a common ancestor fact") would benefit from native graph traversal. Deferred to graph-DB integration research — see Stronghold issue #1233.
- **Q59.6.** When a source's reliability rebuilds above the floor after a LESSON minted, the LESSON itself remains. Reviewer call: should rebuilt-reliability mint an OPINION-tier counter-claim, or should the LESSON be allowed to age out via standard decay? Lean toward the latter; a counter-LESSON would create churn.
