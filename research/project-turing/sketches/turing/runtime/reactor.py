"""RealReactor: blocking-tick loop with ThreadPoolExecutor side channel.

Deliberate divergence from main's pure-asyncio Reactor. The blocking-tick
shape gives us deterministic evaluation order, O(1) blocking gates on
handlers, and an obvious place to measure drift. Slow work — LLM calls,
provider quota probes, contradiction drafting — goes through `spawn()`
and lands in executor workers. Handlers never block on I/O; they submit
and collect.

Contract mirrors `turing.reactor.FakeReactor`:

  reactor.register(handler: Callable[[int], None])
  reactor.spawn(fn, *args, **kwargs) -> Future
  reactor.tick_count: int

Plus the production-only surface:

  reactor.run_forever()         — blocking tick loop; call on main thread
  reactor.stop()                — sets the stop event; drains executor
  reactor.get_status()          — snapshot of tick / drift / executor state
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger("turing.runtime.reactor")


@dataclass(frozen=True)
class ReactorStatus:
    tick_count: int
    tick_rate_hz: int
    drift_ms_p99: float
    executor_active: int
    executor_queued: int
    running: bool


class RealReactor:
    """Blocking-tick reactor with a thread-pool side channel for slow work."""

    def __init__(
        self,
        *,
        tick_rate_hz: int = 1000,
        executor_workers: int = 8,
        drift_samples: int = 1024,
    ) -> None:
        if tick_rate_hz <= 0:
            raise ValueError("tick_rate_hz must be positive")
        if executor_workers <= 0:
            raise ValueError("executor_workers must be positive")

        self._tick_rate_hz = tick_rate_hz
        self._period_ns = 1_000_000_000 // tick_rate_hz
        self._handlers: list[Callable[[int], None]] = []
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(
            max_workers=executor_workers,
            thread_name_prefix="turing-exec",
        )
        self._running = False
        self._drift_samples = drift_samples
        self._drift_ns: list[int] = []
        self.tick_count: int = 0

    # -- registration --

    def register(self, handler: Callable[[int], None]) -> None:
        self._handlers.append(handler)

    # -- side channel --

    def spawn(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future[Any]:
        return self._executor.submit(fn, *args, **kwargs)

    # -- loop --

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
                        logger.exception(
                            "handler raised during tick %d", self.tick_count
                        )

                next_at_ns += self._period_ns
                now_ns = time.monotonic_ns()
                remaining_ns = next_at_ns - now_ns
                if remaining_ns > 0:
                    time.sleep(remaining_ns / 1_000_000_000)
                else:
                    # Behind schedule. Record drift, don't sleep.
                    self._record_drift(-remaining_ns)
                    # Reset next_at so drift doesn't compound forever.
                    if -remaining_ns > self._period_ns * 10:
                        next_at_ns = time.monotonic_ns()
        finally:
            self._running = False
            self._executor.shutdown(wait=True, cancel_futures=False)

    def stop(self) -> None:
        self._stop.set()

    # -- observability --

    def _record_drift(self, drift_ns: int) -> None:
        self._drift_ns.append(drift_ns)
        if len(self._drift_ns) > self._drift_samples:
            self._drift_ns = self._drift_ns[-self._drift_samples :]

    def get_status(self) -> ReactorStatus:
        drift_p99_ms = 0.0
        if self._drift_ns:
            sorted_drift = sorted(self._drift_ns)
            idx = min(len(sorted_drift) - 1, int(len(sorted_drift) * 0.99))
            drift_p99_ms = sorted_drift[idx] / 1_000_000
        # ThreadPoolExecutor doesn't expose queue depth cleanly; introspect.
        queued = self._executor._work_queue.qsize()  # type: ignore[attr-defined]
        active = max(0, len(self._executor._threads) - queued)  # best-effort
        return ReactorStatus(
            tick_count=self.tick_count,
            tick_rate_hz=self._tick_rate_hz,
            drift_ms_p99=drift_p99_ms,
            executor_active=active,
            executor_queued=queued,
            running=self._running,
        )
