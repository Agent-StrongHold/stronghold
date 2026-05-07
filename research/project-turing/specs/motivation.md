# Spec 9 — Motivation: priority ladder, pressure vector, fit vector, backlog, dispatch

*The Conduit's to-do list. Every candidate action lives here; the dispatcher reads it; the Reactor ticks it. Class priority is how much we want to do something; the pressure-times-fit bonus is how cheap it is to do right now. Score decides queue position.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md), [write-paths.md](./write-paths.md).
**Depended on by:** [scheduler.md](./scheduler.md), [daydreaming.md](./daydreaming.md), [tuning.md](./tuning.md), [detectors/README.md](./detectors/README.md).

---

## Current state

- `main` has the 1000Hz Reactor and a `QuotaTracker`, but no proactive-work dispatcher and no priority-scored backlog.
- Request handling is request-driven: a request arrives, the pipeline classifies and routes, and no prioritization happens across concurrent candidates because there are no concurrent candidates.
- Free-tier token expiration is not tracked as actionable pressure.

## Target

A single backlog data structure holds every candidate action across all priority classes, proactive and reactive alike. The dispatcher computes a score per item, runs two loops at different cadences, and fires items in descending score order subject to readiness and capacity.

The scoring formula is:

```
score(item) = priority_base(item.class) + max(pressure_vec ⊙ fit_vec(item))
chosen_model(item) = argmax(pressure_vec ⊙ fit_vec(item))
```

Where `⊙` is elementwise multiplication. The **max component** of the product vector is the pressure bonus; its **argmax** is the chosen model pool for dispatch. Both fall out of a single computation.

## Acceptance criteria

### Priority ladder

- **AC-9.1.** `priority_base` maps class labels to the anchored scale: `P0=1_000_000, P1=750_000, P2=500_000, P3=250_000, P4=100_000, P5=50_000, P10=10_000, P20=1_000, P30=100, P40=10, P50=1, P60=0.1, P70=0.01`. Between anchors, interpolation is log-linear. Lookup test for each anchor and for interpolated positions.
- **AC-9.2.** `priority_base` is a pure function. No state mutation on lookup. Test.

### Pressure and fit vectors

- **AC-9.3.** `pressure_vec` has one component per registered model pool. Each component is in `[0.0, PRESSURE_MAX]` (default `PRESSURE_MAX = 5_000`; runtime-tunable). Test asserts shape and range clamping.
- **AC-9.4.** `fit_vec` on an item has the same shape as `pressure_vec`, with each component in `[0.0, 1.0]`. Sparse by convention — most items have non-zero fit for at most a few pools. Test asserts range.
- **AC-9.5.** An item with `fit_vec = [0, 0, 0, ...]` (no fit for any pool) scores purely on `priority_base`; no pressure bonus. Test.
- **AC-9.6.** Elementwise product `pressure_vec ⊙ fit_vec` is computed in `O(len(pressure_vec))`. Benchmark test with realistic vector sizes.

### Scoring and dispatch

- **AC-9.7.** `score(item) = priority_base(item.class) + max(pressure_vec ⊙ fit_vec(item))`. Unit test over a fixture of items with known vectors.
- **AC-9.8.** `chosen_model(item) = argmax(pressure_vec ⊙ fit_vec(item))`. When the max is tied across multiple pools, a deterministic tiebreaker (declared pool order) picks one. Test.
- **AC-9.9.** Cross-band reordering is allowed when `max(pressure ⊙ fit)` exceeds the class gap to the next band. This is feature, not bug: pressure-worth-spending may outrank class-priority. Property test over random pressure vectors asserts scoring mathematics; behavioral test asserts the Codestral-on-low-priority-RASO case fires correctly.
- **AC-9.10.** Starvation guard: within a given model pool, class priority dominates (an item with higher class always sits above a lower-class item on the same pool, regardless of pressure). Property test.

### Backlog and loops

- **AC-9.11.** Backlog insertion is `O(log n)`. Eviction is `O(log n)`. Dynamic-priority update (for daydream items whose score changes with pressure) is `O(log n)`. Benchmark test.
- **AC-9.12.** Per-tick event loop's total work completes within `TICK_BUDGET_MS` (default 1 ms) on reference hardware. Benchmark test under realistic backlog size.
- **AC-9.13.** Action loop runs every `ACTION_CADENCE_TICKS` ticks (default 10). Test asserts cadence over a simulated tick stream.
- **AC-9.14.** Action loop's sweep considers only the top `TOP_X` items (default 5). Benchmark test asserts work is bounded independent of backlog depth.
- **AC-9.15.** An item fires only if its class-specific `readiness()` predicate returns true AND the pipeline has capacity for its cost. Test.
- **AC-9.16.** Multiple items with different `chosen_model` can fire concurrently in the same sweep, subject to `MAX_CONCURRENT_DISPATCHES` (default 4). Single-pool concurrency is serialized by class priority within that pool. Test.

### Dispatch decision observation

- **AC-9.17.** Every dispatch writes an observation record (see [schema.md](./schema.md) addition): `dispatched_item_id`, `chosen_model`, `score`, `pressure_vec` at decision time, `fit_vec` snapshot, timestamp. Test asserts the write happens on every dispatch.
- **AC-9.18.** A dispatched item that is preempted (e.g., by an incoming P1) writes a preemption record with the interrupt reason. Test.

## Implementation

### 9.1 Priority scale

```python
PRIORITY_ANCHORS: dict[int, float] = {
    0:  1_000_000.0,
    1:    750_000.0,
    2:    500_000.0,
    3:    250_000.0,
    4:    100_000.0,
    5:     50_000.0,
    10:    10_000.0,
    20:     1_000.0,
    30:       100.0,
    40:        10.0,
    50:         1.0,
    60:         0.1,
    70:         0.01,
}


def priority_base(p: int) -> float:
    """Log-linear interpolation between anchored values.

    p is the class number; smaller p means higher priority.
    """
    if p in PRIORITY_ANCHORS:
        return PRIORITY_ANCHORS[p]
    keys = sorted(PRIORITY_ANCHORS.keys())
    lo = max(k for k in keys if k < p)
    hi = min(k for k in keys if k > p)
    # Interpolate in log space.
    import math
    log_lo = math.log10(PRIORITY_ANCHORS[lo])
    log_hi = math.log10(PRIORITY_ANCHORS[hi])
    t = (p - lo) / (hi - lo)
    return 10 ** (log_lo + t * (log_hi - log_lo))
```

Band characteristics:

- P0–P5 are tightly spaced (user-facing, hard SLAs). Cross-band reordering requires very high pressure.
- P10–P20 are proactive work (RASO). Pressure at the order of thousands can reorder within this range.
- P30–P70 are open-ended exploration and daydreaming. Small pressure values move things around easily.

### 9.2 Pressure vector

Maintained by the Motivation component. Each pool's component is updated when:

- Token usage is recorded against the pool.
- A provider window ticks (RPM reset, daily reset, etc.).

```python
@dataclass
class ModelPool:
    name: str                       # e.g. "gemini-2.0-pro"
    window_kind: str                # "rpm" | "daily" | "monthly" | "rolling_hours"
    window_duration: timedelta
    tokens_allowed: int
    tokens_used: int
    window_started_at: datetime

    @property
    def pressure(self) -> float:
        """Scalar pressure contribution for this pool."""
        headroom = self.tokens_allowed - self.tokens_used
        if headroom <= 0:
            return 0.0
        time_remaining = (self.window_started_at + self.window_duration) - datetime.now(UTC)
        if time_remaining.total_seconds() <= 0:
            return 0.0
        # tokens-about-to-expire per second of remaining window, scaled
        rate = headroom / time_remaining.total_seconds()
        return min(rate * PRESSURE_RATE_COEFFICIENT, PRESSURE_MAX)
```

`PRESSURE_RATE_COEFFICIENT` is runtime-tuned (see [tuning.md](./tuning.md)). `PRESSURE_MAX` caps the per-pool contribution to prevent any one pool from dominating.

### 9.3 Fit vector on items

An item declares its fit as a dict keyed by pool name; missing pools default to 0.0.

```python
@dataclass
class BacklogItem:
    item_id: str
    class_: int                            # priority class; smaller = higher
    kind: str                              # "p0_scheduled", "p1_chat", "raso_candidate", "daydream_candidate", ...
    payload: Any
    fit: dict[str, float] = field(default_factory=dict)     # pool_name -> fit [0,1]
    readiness: Callable[[PipelineState], bool] = always_ready
    cost_estimate_tokens: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    dynamic_priority: Callable[[PressureVec], float] | None = None
```

Most items have static `class_`. A few (daydream candidates) use `dynamic_priority` to recompute score as pressure evolves.

### 9.4 Score and dispatch

```python
def score(item: BacklogItem, pressure: PressureVec) -> tuple[float, str]:
    if item.dynamic_priority is not None:
        base = item.dynamic_priority(pressure)
    else:
        base = priority_base(item.class_)

    # Elementwise product → max component + argmax
    best_pool, best_bonus = "", 0.0
    for pool_name, pool_pressure in pressure.items():
        fit = item.fit.get(pool_name, 0.0)
        bonus = pool_pressure * fit
        if bonus > best_bonus:
            best_bonus = bonus
            best_pool = pool_name
    return base + best_bonus, best_pool
```

`best_pool` is the `chosen_model` for dispatch. If `best_bonus == 0`, the item runs on whichever pool its `payload.preferred_model` indicates (or the default pool for its kind).

### 9.5 The two loops

```python
class Motivation:
    backlog: SortedContainer[BacklogItem]   # sorted by score desc
    pressure: PressureVec
    reactor: Reactor                         # real or FakeReactor

    def on_tick(self, tick: int) -> None:       # per-tick event loop
        self._ingest_new_events()
        self._evict_stale()
        self._update_dynamic_priorities()
        if tick % ACTION_CADENCE_TICKS == 0:
            self._action_sweep()

    def _action_sweep(self) -> None:
        dispatched_any = False
        for item in self.backlog.top(TOP_X):
            if len(self._in_flight) >= MAX_CONCURRENT_DISPATCHES:
                break
            if not item.readiness(self._pipeline_state()):
                continue
            if not self._pool_has_capacity(item):
                continue
            score_val, chosen_pool = score(item, self.pressure)
            self._dispatch(item, chosen_pool, score_val)
            self._write_dispatch_observation(item, chosen_pool, score_val)
            dispatched_any = True
```

Event sources that feed `_ingest_new_events()`:

- Scheduler (P0) — upcoming deliveries becoming early-executable.
- Request intake (P1, P3) — new user request arrives.
- Event triggers (P2) — alarms, webhooks.
- Backlog submissions (P4, P5–10) — user-added tasks.
- RASO detectors (P11–P20) — propose candidates.
- Daydream producer (P20+) — last-resort candidate.

### 9.6 Readiness predicates per class

```python
def readiness_p0(state: PipelineState, item: BacklogItem) -> bool:
    return state.now >= item.payload.early_executable_start

def readiness_p1(state: PipelineState, item: BacklogItem) -> bool:
    return state.user_session_open(item.payload.session_id)

def readiness_p4(state: PipelineState, item: BacklogItem) -> bool:
    return state.pool_has_headroom(item.payload.preferred_model)

def readiness_raso(state: PipelineState, item: BacklogItem) -> bool:
    return (item.payload.detector_context_valid()
            and state.pool_has_headroom(item.fit_primary_pool))

def readiness_daydream(state: PipelineState, item: BacklogItem) -> bool:
    return (score(item, state.pressure)[0] > DAYDREAM_FIRE_FLOOR
            and state.in_scheduled_quiet_zone() is False)
```

`DAYDREAM_FIRE_FLOOR` is the minimum score required for daydream candidates to fire. Tuned runtime.

### 9.7 Configuration constants

```python
# Cadences and windows
TICK_BUDGET_MS:                   int = 1
ACTION_CADENCE_TICKS:             int = 10
TOP_X:                            int = 5
MAX_CONCURRENT_DISPATCHES:        int = 4

# Pressure calibration (seeds — runtime-tuned; see tuning.md)
PRESSURE_MAX:                     float = 5_000.0
PRESSURE_RATE_COEFFICIENT:        float = 1.0
DAYDREAM_FIRE_FLOOR:              float = 10.0  # ~P40

# Seeds are starting points. Any deployment running under seeds for long
# should be considered under-tuned.
```

## Open questions

- **Q9.1.** Log-linear interpolation between anchors — reasonable default but arbitrary. Alternative: piecewise-exponential with explicit per-gap decay rates. Leaving log-linear as the seed; tuning can propose a different shape.
- **Q9.2.** `PRESSURE_MAX = 5000` caps each pool's contribution to ~P10-band territory. That means pressure alone cannot force a sub-P10 item above a P5 user-waiting item under seeds. Cross-band reordering below P10 is free; above requires either runtime-raised `PRESSURE_MAX` or a special path. Intentional choice worth naming.
- **Q9.3.** `MAX_CONCURRENT_DISPATCHES = 4` is a guess. Actual safe concurrency depends on downstream LLM client + network + observability load.
- **Q9.4.** `DAYDREAM_FIRE_FLOOR` is a single scalar; consider making it per-pool so daydream firing on a pressured pool is independent of daydream firing on a quiet pool.
- **Q9.5.** The dispatch-decision observation (AC-9.17) is written as an OBSERVATION-tier memory with `source = I_DID`. That's a lot of noise in the general episodic store — might need its own table or a retention policy.
