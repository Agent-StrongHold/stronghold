# Spec 7 — Daydreaming: per-model candidate producer of last resort

*Daydreaming is no longer a Reactor trigger that owns its own firing decision. It is a family of per-model candidate producers that submit low-priority items to the motivation backlog. The motivation component decides when they fire, via score and readiness. Daydreaming's only job is to propose seeds and write I_IMAGINED memories when selected.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md), [retrieval.md](./retrieval.md), [motivation.md](./motivation.md).
**Depended on by:** —

---

## Current state

- `main` has no daydreaming producer.
- Any prior Project Turing draft that made daydreaming own trigger evaluation or pre-reset escalation is superseded by this spec. Those behaviors live in [motivation.md](./motivation.md) now.

## Target

One daydream producer per model pool (or one parametric producer parametrized by pool). Each producer:

1. Watches its pool's pressure component.
2. When the pool's fit-weighted pressure is non-zero, submits a candidate to the motivation backlog with `class_` chosen from the P20+ band and `dynamic_priority = f(pressure)` so its score rises with pressure.
3. When selected by the dispatcher, runs a bounded pass that retrieves from durable memory, generates I_IMAGINED content via the pool's model, and writes the output as HYPOTHESIS or OBSERVATION tier with `source = I_IMAGINED`.
4. Never writes to durable tiers. Never writes with `source = I_DID`. Both guarantees structural, not policy.

## Acceptance criteria

### Source and tier locks (hard structural guarantees)

- **AC-7.1.** A daydream pass can only write memories with `source = SourceKind.I_IMAGINED`. The `DaydreamWriter` class has no API for emitting `I_DID`. Attempting to construct a memory with `source != I_IMAGINED` through the daydream code path raises. Negative test exists.
- **AC-7.2.** A daydream pass cannot write into `REGRET`, `ACCOMPLISHMENT`, `AFFIRMATION`, or `WISDOM` tiers. The `DaydreamWriter` has no API method for any durable tier. Negative test over each attempted tier.
- **AC-7.3.** A daydream pass cannot mutate any existing memory. `DaydreamWriter` is write-only against new I_IMAGINED HYPOTHESIS/OBSERVATION rows. Test asserts no update paths exist.

### Producer behavior

- **AC-7.4.** Each registered model pool has an associated daydream producer. A pool with pressure > 0 emits at most one candidate into the backlog at any time (no candidate-flooding). Test.
- **AC-7.5.** A candidate's `dynamic_priority` is a pure function of `pressure_vec`; re-evaluated by the motivation component during its priority-update step. Test asserts the function is stateless.
- **AC-7.6.** A candidate with score below `DAYDREAM_FIRE_FLOOR` (see [motivation.md](./motivation.md)) sits in the backlog unfired. As pressure rises, its score rises; when it crosses the floor, it becomes eligible. Test over a simulated pressure curve.
- **AC-7.7.** A candidate whose model pool's pressure drops to zero is evicted from the backlog; no stale daydream candidates accumulate. Test.

### Execution

- **AC-7.8.** When dispatched, a pass completes within `DAYDREAM_TOKENS_PER_PASS` (default 2,000) tokens. Exceeding halts at the boundary; any writes already committed stay; no partial LLM call is persisted. Test.
- **AC-7.9.** A pass completes within `DAYDREAM_WRITES_PER_PASS` (default 5) memory writes. Exceeding halts. Test.
- **AC-7.10.** A preempted pass (e.g., P1 arrives) discards any uncommitted output and leaves no partial memory. Test with forced preemption.
- **AC-7.11.** A micro-pass (single seed, single LLM call, single write) completes within `DAYDREAM_MICRO_PASS_MAX_MS` (default 500 ms). Benchmark.

### Provenance and auditability

- **AC-7.12.** Every daydream pass writes a session marker: `tier = OBSERVATION`, `source = I_DID`, containing start/end timestamps, provider used, tokens consumed, write count, seed memory_id. The marker is the Conduit's first-person record *that the pass happened* — the content was imagined, but the act of imagining is I_DID. Test.
- **AC-7.13.** Re-running a daydream pass with the same seed and the same LLM response (test fixture pins the LLM) produces identical I_IMAGINED rows modulo timestamp. Deterministic test.
- **AC-7.14.** Each I_IMAGINED memory carries `origin_episode_id` pointing to the session-marker memory_id, linking the family. Test asserts the reference.

### Promotion (not upgrade)

- **AC-7.15.** An I_IMAGINED HYPOTHESIS cannot have its `source` field upgraded to `I_DID` ever. If a real I_DID experience later matches the hypothesis, a new I_DID memory is minted with `origin_episode_id` pointing at the I_IMAGINED. The I_IMAGINED memory remains I_IMAGINED for life. Test asserts the upgrade path does not exist.

### Quiet zones

- **AC-7.16.** Daydream readiness returns false when the current time falls inside any interval returned by the scheduler's `quiet_zones()` (see [scheduler.md](./scheduler.md)). Test over a quiet-zone fixture.

## Implementation

### 7.1 Producer

```python
class DaydreamProducer:
    """One instance per model pool. Submits candidates to motivation."""

    pool_name: str
    self_id: str
    active_candidate_id: str | None = None

    def on_tick(self, motivation: Motivation) -> None:
        pressure_component = motivation.pressure.get(self.pool_name, 0.0)
        if pressure_component == 0.0:
            self._evict_if_present(motivation)
            return
        if self.active_candidate_id is not None:
            return  # already have one in the backlog
        self.active_candidate_id = motivation.insert(self._build_candidate())

    def _build_candidate(self) -> BacklogItem:
        return BacklogItem(
            item_id=new_item_id(),
            class_=20,          # starts at P20; dynamic_priority lifts it
            kind="daydream_candidate",
            payload=DaydreamPayload(pool_name=self.pool_name, self_id=self.self_id),
            fit={self.pool_name: 1.0},   # only that pool
            readiness=readiness_daydream,
            dynamic_priority=lambda pv: self._dynamic_priority(pv),
            cost_estimate_tokens=DAYDREAM_TOKENS_PER_PASS,
        )

    def _dynamic_priority(self, pressure: PressureVec) -> float:
        """Returns a priority_base that rises with pool-specific pressure.

        At pressure=0: returns priority_base(P_INF) → ~0.
        At pressure=PRESSURE_MAX: returns priority_base(P30) ≈ 100.
        Continuous monotonic; never crosses into P20 band under seed coefficients.
        """
        p = pressure.get(self.pool_name, 0.0)
        if p <= 0.0:
            return priority_base(99)
        # Map [0, PRESSURE_MAX] to priority classes [99, 21].
        class_f = 99.0 - 78.0 * (p / PRESSURE_MAX)
        return priority_base(int(class_f))
```

When dispatched, the `DaydreamPayload` is executed by a `DaydreamExecutor` that uses the `DaydreamWriter`.

### 7.2 Writer with structural locks

```python
class DaydreamWriter:
    """Only API: write HYPOTHESIS or OBSERVATION at source=I_IMAGINED.

    No method for writing other sources or durable tiers. The locks are
    structural; they cannot be bypassed without editing this class.
    """

    def __init__(self, repo: EpisodicRepo, self_id: str, session_id: str) -> None:
        self._repo = repo
        self._self_id = self_id
        self._session_id = session_id

    def write_hypothesis(self, content: str, intent: str, context: dict) -> str:
        return self._repo.insert(EpisodicMemory(
            memory_id=new_memory_id(),
            self_id=self._self_id,
            tier=MemoryTier.HYPOTHESIS,
            source=SourceKind.I_IMAGINED,   # hardcoded
            content=content,
            weight=0.3,
            intent_at_time=intent,
            origin_episode_id=self._session_id,
            context=context,
        ))

    def write_observation(self, content: str, context: dict) -> str:
        return self._repo.insert(EpisodicMemory(
            memory_id=new_memory_id(),
            self_id=self._self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_IMAGINED,   # hardcoded
            content=content,
            weight=0.3,
            origin_episode_id=self._session_id,
            context=context,
        ))

    # Deliberately no: write_regret, write_accomplishment, write_wisdom,
    # write_affirmation, write_i_did_*.
```

The repository also double-checks: any insert from a `DaydreamWriter` context with a durable tier or I_DID source raises before reaching the DB.

### 7.3 Pass sequence

1. **Seed selection.** Pick a seed from the durable store, weighted by recency of last access and a bias toward unresolved REGRETs (REGRETs whose `supersedes` chain has no LESSON). Counter-weight toward ACCOMPLISHMENT seeds by `ACCOMPLISHMENT_BIAS` (default 0.5) to prevent rumination.
2. **Retrieve.** Pull related memories by `intent_at_time` family and topic cluster. Include I_IMAGINED memories from prior daydreams only if explicit (keeps simulated chains traceable). Source filter defaults to `{I_DID}`.
3. **Imagine.** Bounded LLM call to the pool's model. System prompt bakes in "you are simulating, not reporting experience." Prompt structure constrains output to one or more atomic claims.
4. **Encode.** Write each claim as HYPOTHESIS (if testable) or OBSERVATION (if descriptive). All with `source = I_IMAGINED`, `origin_episode_id` = session marker.
5. **Mark.** Session marker written at pass end: OBSERVATION, I_DID, records pass metadata.

### 7.4 Configuration constants

```python
DAYDREAM_TOKENS_PER_PASS:     int   = 2_000
DAYDREAM_WRITES_PER_PASS:     int   = 5
DAYDREAM_MICRO_PASS_MAX_MS:   int   = 500
ACCOMPLISHMENT_BIAS:          float = 0.5
```

All runtime-tunable.

## Open questions

- **Q7.1.** `dynamic_priority` maps linear pressure to linear class-number space — so it rises as P99 → P30 linearly with pressure. The actual f(pressure) probably wants a sigmoid or threshold effect (no lift until pressure is meaningful, then rapid lift as expiration approaches). Seeded linear; tuning can reshape.
- **Q7.2.** Seed bias toward unresolved REGRETs + ACCOMPLISHMENT counter-bias is a guess. Rumination risk is real; the counter-bias may need to be adaptive based on observed affect distribution in recent daydreams.
- **Q7.3.** Daydream retrieval patterns could subtly bias what live routing notices (exposure effects). Instrumentation should record which clusters daydream pulled from and whether live routing later clusters similarly.
- **Q7.4.** The pool's model choice for a daydream pass is implicit from `pool_name`. A provider with multiple model variants (Gemini Pro vs Flash) may want the daydream producer to pick the variant; probably out of scope here — pool is atomic.
- **Q7.5.** `ACCOMPLISHMENT_BIAS = 0.5` is structure-preserving rather than specific. Open how it should adapt based on observed affect distribution.
