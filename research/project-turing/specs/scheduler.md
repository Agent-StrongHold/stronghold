# Spec 10 — Scheduler: P0 delivery-deadline work

*The only priority class whose timing is externally constrained. Scheduled items have a delivery time that must be met; work can be performed anywhere in the early-executable window before it. The scheduler tracks these items, emits them into the motivation backlog when they become early-executable, and holds their outputs until delivery time.*

**Depends on:** [motivation.md](./motivation.md).
**Depended on by:** —

---

## Current state

- `main` has no scheduler. All work is request-driven.

## Target

A scheduler maintains a list of upcoming deliveries, each with:

- A `delivery_time` (when the output must be delivered).
- An `early_executable_start` (when the work may begin; defaults to delivery_time minus a configurable prepare-window).
- An `estimated_duration` (so the motivation component can reserve the dream quiet-zone around it).
- A payload and a delivery callback.

The scheduler inserts items into the motivation backlog at P0 when their early-executable window opens. Output produced early is held in a delivery buffer until the delivery callback is invoked at `delivery_time`.

## Acceptance criteria

### Lifecycle

- **AC-10.1.** A scheduled item with `early_executable_start > now()` sits in the scheduler's pending list, not in the backlog. Test asserts the backlog does not contain the item until its window opens.
- **AC-10.2.** When `now() >= early_executable_start`, the scheduler inserts the item into the motivation backlog at class P0. Test asserts insertion within one tick of the crossover.
- **AC-10.3.** A scheduled item that has already fired and produced output is not re-inserted. Idempotent insertion. Test over duplicate clock crossings.
- **AC-10.4.** When `now() >= delivery_time`, the scheduler invokes the delivery callback with the stored output and removes the item. Test asserts callback invocation at the correct tick.

### Early execution and holding

- **AC-10.5.** If a P0 item executes before `delivery_time`, its output is stored in a delivery buffer keyed by item_id. Test asserts the output is not delivered early.
- **AC-10.6.** Operator-initiated "deliver early" command flushes the delivery buffer for a specific item. Test asserts the command path.
- **AC-10.7.** A scheduled item whose execution fails before `delivery_time` is retried. Retry cadence is bounded by `MAX_RETRIES` (default 3) and `RETRY_COOLDOWN` (default exponential backoff from 1 minute). Test over induced failures.
- **AC-10.8.** A scheduled item whose execution has not produced output by `delivery_time - GRACE_WINDOW` raises a missed-deadline REGRET and attempts an immediate final retry. Test asserts the REGRET is minted.

### Quiet zone around scheduled events

- **AC-10.9.** The scheduler exposes `quiet_zones()` returning the list of `(start, end)` intervals where daydreaming should be suppressed. Each zone extends `5 * average_daydream_duration` before `early_executable_start` and after `max(execution_end, delivery_time)`. Test asserts correct interval computation.
- **AC-10.10.** The motivation component consults `quiet_zones()` in the daydream readiness predicate; a daydream candidate whose evaluation time falls in a zone returns not-ready. Test asserts daydreaming is suppressed during zones.

### Persistence

- **AC-10.11.** Scheduled items persist across restarts. A restart in the middle of an early-executable window preserves the item's position (still at P0, still not yet fired or re-fires if interrupted). Integration test with simulated restart.
- **AC-10.12.** Delivery buffer contents persist across restarts. Items whose output was produced but not yet delivered survive a crash. Test.

## Implementation

### 10.1 Scheduled item schema

```python
@dataclass(frozen=True)
class ScheduledItem:
    item_id: str
    self_id: str
    delivery_time: datetime
    early_executable_start: datetime
    estimated_duration: timedelta
    payload: Any
    delivery_callback_name: str            # indirection so callbacks survive restart
    preferred_model: str | None = None
    fit: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

Defaults: if `early_executable_start` is not set, compute as `delivery_time - DEFAULT_PREPARE_WINDOW` (default 10 minutes). If the estimated_duration is not set, use `DEFAULT_ESTIMATED_DURATION` (default 30 seconds).

### 10.2 Scheduler loop

Runs as its own producer on the Motivation's per-tick event loop:

```python
class Scheduler:
    pending: list[ScheduledItem]
    delivery_buffer: dict[str, DeliveryRecord]

    def on_tick(self, motivation: Motivation) -> None:
        now = datetime.now(UTC)
        for item in list(self.pending):
            if item.early_executable_start <= now:
                motivation.insert(self._to_backlog_item(item))
                self.pending.remove(item)
        self._check_deliveries(now)
        self._retry_failed_executions(now)

    def _check_deliveries(self, now: datetime) -> None:
        for item_id, record in list(self.delivery_buffer.items()):
            if now >= record.delivery_time:
                callback = CALLBACK_REGISTRY.get(record.delivery_callback_name)
                callback(record.output)
                del self.delivery_buffer[item_id]
```

### 10.3 Execution and holding

When the motivation dispatcher picks a P0 backlog item and fires it:

```python
def on_p0_dispatch_complete(item: BacklogItem, output: Any, scheduler: Scheduler) -> None:
    scheduler.delivery_buffer[item.item_id] = DeliveryRecord(
        delivery_time=item.payload.delivery_time,
        output=output,
        delivery_callback_name=item.payload.delivery_callback_name,
        produced_at=datetime.now(UTC),
    )
```

The output sits in `delivery_buffer` until the scheduler's tick loop sees that `delivery_time` has arrived and invokes the callback.

### 10.4 Quiet zones

```python
def quiet_zones(scheduler: Scheduler) -> list[tuple[datetime, datetime]]:
    avg_daydream = recent_avg_daydream_duration()   # observed; defaults to 500ms
    buffer = 5 * avg_daydream
    zones = []
    for item in scheduler.pending:
        zones.append((item.early_executable_start - buffer, item.early_executable_start))
    for item_id, record in scheduler.delivery_buffer.items():
        zones.append((record.delivery_time - buffer, record.delivery_time + buffer))
    return zones
```

### 10.5 Configuration constants

```python
DEFAULT_PREPARE_WINDOW:        timedelta = timedelta(minutes=10)
DEFAULT_ESTIMATED_DURATION:    timedelta = timedelta(seconds=30)
MAX_RETRIES:                   int = 3
RETRY_COOLDOWN_BASE_S:         int = 60
GRACE_WINDOW:                  timedelta = timedelta(seconds=5)
DAYDREAM_QUIET_MULTIPLE:       int = 5     # 5x average daydream duration
```

## Open questions

- **Q10.1.** `DEFAULT_PREPARE_WINDOW = 10 minutes` is a coarse default. Realistic scheduling needs per-task-class prepare windows — a short acknowledgment could need 30 seconds; a long report could need 30 minutes. Schedule items should probably carry their own prepare window rather than rely on a global default.
- **Q10.2.** Missed-deadline REGRET: the minted REGRET per AC-10.8 is a self-implicating entry. But the failure cause might be external (provider outage) rather than a scheduling mistake. Does the REGRET need a `cause_external: bool` field, or is the Conduit's regret about its own choice to have scheduled this at all?
- **Q10.3.** Delivery callback registry: callbacks identified by name for restart-survivability. Need an import-time registration pattern so the registry is populated before the scheduler reads items from persistence.
- **Q10.4.** Multiple scheduled items stacking in the same window — their quiet zones overlap. The motivation component should union zones, not stack them. Covered by `quiet_zones()` returning intervals; naming it here so the implementation doesn't forget.
- **Q10.5.** Distributed scheduling (multiple Conduit processes seeing the same scheduled item) is not in scope. Single-instance assumption.
