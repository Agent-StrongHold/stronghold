# Spec 20 — RealReactor: blocking-tick + side-channel executor

*The runtime's heartbeat. Deliberate divergence from main's pure-asyncio Reactor: research wants deterministic evaluation order, hard blocking-gate budgets per handler, and a single observable `tick_count`. Slow work goes through `spawn()` to a `ThreadPoolExecutor`, which keeps the tick loop O(handler_count) per tick.*

**Depends on:** —
**Depended on by:** all runtime modules.

---

## Current state

`runtime/reactor.py::RealReactor` built; 8 tests; no spec.

## Target

A blocking-tick loop with a side-channel `ThreadPoolExecutor` for slow I/O. Documented divergence from main's asyncio model. `FakeReactor` (in `turing/reactor.py`, separate from runtime) implements the same Protocol for tests; its `spawn()` runs synchronously.

## Acceptance criteria

### Tick loop

- **AC-20.1.** `RealReactor(tick_rate_hz=N, executor_workers=K)` validates `tick_rate_hz > 0` and `executor_workers > 0`, raising `ValueError` otherwise. Test.
- **AC-20.2.** `run_forever()` is blocking. It maintains a target tick interval via `time.monotonic_ns()` (not wall clock); `time.sleep()` is used to wait until the next tick. Test asserts target rate is approximately honored over a 1s window (within ±20%).
- **AC-20.3.** `tick_count` increments by exactly 1 each tick. Test asserts monotonicity.
- **AC-20.4.** Each registered handler is called once per tick with the current `tick_count` as argument. Handlers are invoked in registration order. Test asserts order.
- **AC-20.5.** Handler exceptions are caught and logged; the tick loop continues. A misbehaving handler does not stop the reactor. Test with a handler that always raises.

### Spawn / executor

- **AC-20.6.** `spawn(fn, *args, **kwargs) -> Future` submits to the internal `ThreadPoolExecutor`. The Future is returned immediately. Test asserts non-blocking behavior.
- **AC-20.7.** `spawn` failures (the wrapped function raising) propagate via the Future's `result()` raising. Test.
- **AC-20.8.** The executor uses a thread name prefix `"turing-exec"` for log tracing. Test asserts at least one thread name matches.

### FakeReactor parity

- **AC-20.9.** `FakeReactor.spawn(fn, *args, **kwargs) -> Future` runs `fn` synchronously and returns an already-resolved Future. Exceptions are captured into the Future. Test asserts both happy and exception paths.
- **AC-20.10.** `FakeReactor.tick(n=1)` calls all handlers `n` times deterministically. Test.

### Drift accounting

- **AC-20.11.** A circular buffer of recent drift samples (default 1024) is maintained. Drift = max(0, actual_tick_time - target_tick_time). Test asserts the buffer is bounded.
- **AC-20.12.** `get_status()` returns `ReactorStatus(tick_count, tick_rate_hz, drift_ms_p99, executor_active, executor_queued, running)`. Test asserts shape and that drift_ms_p99 is non-negative.
- **AC-20.13.** When drift is consistently high (handlers exceed budget), `get_status().drift_ms_p99` reflects it. Documented as the operator's signal that a tick is overcommitted. No automatic mitigation. Test asserts elevated drift after intentionally slow handler.

### Stop semantics

- **AC-20.14.** `stop()` sets a flag; `run_forever()` exits at the next tick boundary. Idempotent. Test asserts second call is a no-op.
- **AC-20.15.** On exit, the executor is shut down with `wait=True` so in-flight slow work finishes. Documented as a graceful shutdown. Test asserts an in-flight Future resolves before stop returns.

### Observability

- **AC-20.16.** `tick_count` is exposed read-only as a public attribute (used by metrics). Test.
- **AC-20.17.** Per-tick handler latency is NOT recorded by default — too much overhead. Operators wanting per-handler timing add it themselves via instrumentation in their handler. Documented.

## Implementation

### 20.1 Tick loop shape

```python
def run_forever(self) -> None:
    self._running = True
    try:
        next_at_ns = time.monotonic_ns()
        while not self._stop.is_set():
            self.tick_count += 1
            for handler in list(self._handlers):
                try:
                    handler(self.tick_count)
                except Exception:
                    logger.exception("handler raised at tick %d", self.tick_count)
            next_at_ns += self._period_ns
            now = time.monotonic_ns()
            remaining = next_at_ns - now
            if remaining > 0:
                time.sleep(remaining / 1e9)
            else:
                self._record_drift(-remaining)
                # If drift is catastrophic, reset to avoid compounding.
                if -remaining > self._period_ns * 10:
                    next_at_ns = time.monotonic_ns()
    finally:
        self._running = False
        self._executor.shutdown(wait=True)
```

### 20.2 Why blocking-tick instead of asyncio

- **Determinism.** A blocking tick guarantees handlers run in registration order; asyncio's task scheduling depends on I/O timing.
- **Hard blocking gate.** Each handler either returns within its budget or it doesn't. Async handlers can `await` and look fast even when they block real work elsewhere.
- **Instrumentation.** Every tick is observable as a synchronous event; no "task started but didn't yield yet" ambiguity.
- **Research goals.** Reproducibility > throughput. The research box is not customer-facing.

### 20.3 Why a thread-pool side channel

LLM calls and HTTP requests are I/O-bound. Putting them on a thread pool keeps the tick loop's per-tick latency O(handler_count × <handler_budget>) and lets I/O overlap with future ticks. The Future-collection pattern (handlers register futures, later ticks poll them) is the canonical interaction.

### 20.4 Configuration constants

```python
DEFAULT_TICK_RATE_HZ:        int = 100         # research default; raise for prod
DEFAULT_EXECUTOR_WORKERS:    int = 8
DEFAULT_DRIFT_SAMPLES:       int = 1024        # circular buffer size
```

## Open questions

- **Q20.1.** Drift compensation strategy: when behind by > 10 periods, we reset `next_at_ns` to skip "catch-up" ticks. Alternative: skip the long-running tick rather than reset. Documented; current behavior is acceptable.
- **Q20.2.** Per-handler timing: should the reactor optionally record per-handler latency for the slowest handlers? Useful for diagnosing drift. Not in the current spec; operators add it as they need it.
- **Q20.3.** Async migration path: if the project ever moves to main's asyncio model, the Provider Protocol and handler shape would need to become async. The current Protocols are sync; documented as "research-time choice."
