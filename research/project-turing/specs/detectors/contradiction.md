# Detector — contradiction

*Detects pairs of durable memories whose content points at each other as contradictory, and whose resolution is already available from a subsequent I_DID outcome. Proposes a LESSON-minting candidate that supersedes both contradictory entries without erasing them.*

**Class:** P14 (seed).
**Depends on:** [`../schema.md`](../schema.md), [`../durability-invariants.md`](../durability-invariants.md), [`../write-paths.md`](../write-paths.md), [`../motivation.md`](../motivation.md), [`./README.md`](./README.md).

---

## Why this detector is the first worked example

- Narrow scope: pairwise check over a small slice of durable memory.
- Clear output: one LESSON per detected contradiction.
- No LLM call required for detection (similarity + content checks only).
- Directly exercises the `supersedes` lineage mechanic (INV-5, INV-6).
- Produces observable test fixtures cheaply.

If the detector pattern works end-to-end for contradiction, subsequent detectors follow the same shape with different detection logic.

## Target

On each tick (bounded work), maintain an index of durable memories by `intent_at_time` family. When a new durable memory is inserted, check it against recent entries in the same family for contradiction. If a contradiction is found and a resolving I_DID OBSERVATION exists, submit a P14 candidate to the motivation backlog proposing a LESSON-minting execution.

When the candidate is dispatched, an execution path reads the contradictory pair plus the resolving observation, drafts a LESSON using a code-capable model (to produce a structured rule), and writes the LESSON with `supersedes` pointing to both contradictory entries.

## Acceptance criteria

### Detection

- **AC-D1.1.** Given two durable memories `A` and `B` with the same `intent_at_time` family, `A.content` and `B.content` mutually contradictory per a structural check (see 11.1 in implementation), and a subsequent I_DID OBSERVATION `C` whose content supports one side, the detector submits exactly one candidate for that triple. Test over fixture.
- **AC-D1.2.** The same triple cannot produce duplicate candidates. A content-hash dedup key (`hash(sorted([A.memory_id, B.memory_id, C.memory_id]))`) is stored in a cheap in-memory set; re-submission is silent. Test asserts idempotence over repeated ticks.
- **AC-D1.3.** A contradiction without a resolving observation does not produce a candidate. The detector waits. Test asserts silence.
- **AC-D1.4.** The detector's per-tick work is `O(k)` where `k` is the number of new durable memories since last tick, not `O(n)` over full durable store. Benchmark test with seed size 10,000.

### Candidate structure

- **AC-D1.5.** Submitted candidate has `class_ = 14`, `kind = "raso_contradiction"`, `fit` preferring a code-capable model pool (seeded: `{"claude-code": 1.0, "gemini-pro": 0.7}`), `cost_estimate_tokens = 2000` seed. Test asserts construction.
- **AC-D1.6.** Payload carries `a_memory_id`, `b_memory_id`, `c_memory_id` for the triple. Test asserts payload schema.
- **AC-D1.7.** Readiness is satisfied if all three memories still exist in the durable store (none deleted — they can't be, per INV-2 — but they could be superseded by a different resolution). If either contradictory memory has `superseded_by` already set, the candidate is evicted. Test asserts eviction path.

### Execution (when dispatched)

- **AC-D1.8.** Dispatching a `raso_contradiction` candidate produces exactly one LESSON memory with `supersedes` pointing at both `A.memory_id` and `B.memory_id` (via lineage chain), `source = I_DID`, `content` explaining the resolution. Test asserts LESSON minting.
- **AC-D1.9.** `A.superseded_by` and `B.superseded_by` are set to the new LESSON's memory_id. Per INV-6, this is one of the permitted in-place updates. Test asserts the lineage is walkable in both directions.
- **AC-D1.10.** If the dispatching execution fails (LLM error, bad response), no memory is minted and the candidate returns to the backlog at the same class with retry cooldown. Test over induced failure.

## Implementation

### 1. Index maintenance

```python
class ContradictionDetector(Detector):
    name = "contradiction"

    _intent_family_index: dict[str, list[str]]    # intent -> [memory_id, ...]
    _submitted_keys: set[str]                      # dedup
    _last_scan_created_at: datetime

    def on_tick(self, state: PipelineState, motivation: Motivation) -> None:
        new_memories = state.durable_repo.since(self._last_scan_created_at)
        for m in new_memories:
            self._add_to_index(m)
            self._check_against_family(m, state, motivation)
        if new_memories:
            self._last_scan_created_at = max(m.created_at for m in new_memories)
```

Index stores memory_ids, keyed by a normalized `intent_at_time` (lowercased, punctuation-stripped). Bounded at `INDEX_MAX_PER_FAMILY` (default 200 memory_ids per family; older entries evicted in favor of higher-weight ones).

### 2. Contradiction check

```python
def _is_contradiction(a: EpisodicMemory, b: EpisodicMemory) -> bool:
    """Structural contradiction: opposite claims under the same intent.

    Checks:
      - Same intent_at_time family.
      - Claims reference same subject/predicate but with opposed polarity.
      - Neither is superseded by the other.
      - Both source = I_DID (I_IMAGINED contradictions are not addressed here).
    """
    if a.intent_at_time != b.intent_at_time:
        return False
    if a.source != SourceKind.I_DID or b.source != SourceKind.I_DID:
        return False
    if a.memory_id == b.memory_id:
        return False
    return _claims_opposed(a.content, b.content)
```

`_claims_opposed` is deliberately simple in this spec — a content-shape check that looks for negation patterns. A more sophisticated version would use an embedding-similarity + polarity-classifier pair, but that's an execution-time concern, not a detection-time concern. Detection is cheap; refinement happens at dispatch.

### 3. Resolution check

```python
def _find_resolution(
    a: EpisodicMemory,
    b: EpisodicMemory,
    repo: EpisodicRepo,
) -> EpisodicMemory | None:
    """Find a later I_DID OBSERVATION that clarifies the contradiction."""
    candidates = repo.find(
        intent_at_time=a.intent_at_time,
        source=SourceKind.I_DID,
        tier=MemoryTier.OBSERVATION,
        created_after=max(a.created_at, b.created_at),
    )
    for c in candidates:
        if _supports_one_side(c.content, a.content, b.content):
            return c
    return None
```

### 4. Candidate building

```python
def _build_candidate(
    a: EpisodicMemory,
    b: EpisodicMemory,
    c: EpisodicMemory,
) -> BacklogItem:
    return BacklogItem(
        item_id=new_item_id(),
        class_=14,
        kind="raso_contradiction",
        payload=ContradictionPayload(
            a_memory_id=a.memory_id,
            b_memory_id=b.memory_id,
            c_memory_id=c.memory_id,
        ),
        fit={"claude-code": 1.0, "gemini-pro": 0.7},
        readiness=_readiness_for_contradiction,
        cost_estimate_tokens=2_000,
    )
```

### 5. Dispatched execution

```python
def execute_contradiction_resolution(payload: ContradictionPayload, repo: EpisodicRepo, llm: LLMClient) -> None:
    a = repo.get(payload.a_memory_id)
    b = repo.get(payload.b_memory_id)
    c = repo.get(payload.c_memory_id)
    if any(m.superseded_by is not None for m in (a, b)):
        return   # stale; abort silently

    draft = llm.draft_lesson(a, b, c)
    lesson = EpisodicMemory(
        memory_id=new_memory_id(),
        self_id=a.self_id,
        tier=MemoryTier.LESSON,
        source=SourceKind.I_DID,
        content=draft.content,
        weight=clamp_weight(MemoryTier.LESSON, draft.initial_weight),
        intent_at_time=a.intent_at_time,
        supersedes=a.memory_id,     # one parent in the dataclass; lineage to b via context
        origin_episode_id=draft.origin_episode_id,
        context={
            "supersedes_via_lineage": [a.memory_id, b.memory_id],
            "resolution_observation": c.memory_id,
        },
    )
    repo.insert(lesson)
    repo.set_superseded_by(a.memory_id, lesson.memory_id)
    repo.set_superseded_by(b.memory_id, lesson.memory_id)
```

The LESSON's schema field `supersedes` holds one parent (first contradictory memory); the second parent is tracked in `context` as `supersedes_via_lineage`. An alternative is a `supersedes: list[str]` field — worth revisiting in a future schema update; for now, context does the job.

## Configuration constants

```python
INDEX_MAX_PER_FAMILY:      int = 200
CONTRADICTION_RETRY_COOLDOWN_S: int = 300
```

## Open questions

- **Q-C.1.** `supersedes` as single-parent is limiting for this use case. The quick workaround is `context["supersedes_via_lineage"]`; the right fix is a `list[str]` field on `EpisodicMemory`. Proposed but deferred to a schema revision.
- **Q-C.2.** Structural `_claims_opposed` check will miss semantic contradictions (paraphrases, implications). That's intentional for the detector (cheap, high-precision-low-recall is better than the reverse here) — the dispatched execution can do the sophisticated check. But it means genuine contradictions will sit undetected for longer than they ideally would.
- **Q-C.3.** If three-way contradictions exist (A contradicts B, B contradicts C, A contradicts C), the detector sees three pairwise contradictions. Each gets its own LESSON, and the result is messy. A more sophisticated detector would cluster before proposing. Future work.
- **Q-C.4.** The resolution observation `C` must be I_DID OBSERVATION — a fact the Conduit observed. If the resolution is only available as a user-reported claim (I_WAS_TOLD), the contradiction sits unresolved until the Conduit independently observes. Intentional but limits detection.
