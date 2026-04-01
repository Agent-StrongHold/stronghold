"""Circuit breaker pattern for failed backends.

Wraps any async callable with three-state fault tolerance:
  CLOSED  → requests flow through, failures tracked
  OPEN    → requests rejected immediately (fast-fail)
  HALF_OPEN → single probe allowed after cooldown

Exponential backoff on repeated probe failures, capped at max_timeout.
Thread-safe via asyncio.Lock for state transitions.
"""

from __future__ import annotations

import asyncio
import enum
import time
from typing import TYPE_CHECKING, Any, TypeVar

from stronghold.types.errors import CircuitOpenError

if TYPE_CHECKING:
    from collections.abc import Awaitable

T = TypeVar("T")


class CircuitState(enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Generic async circuit breaker.

    Parameters
    ----------
    name:
        Human-readable name for logging/stats.
    failure_threshold:
        Consecutive failures before tripping to OPEN.
    recovery_timeout:
        Base cooldown (seconds) before allowing a probe.
    max_timeout:
        Maximum cooldown after exponential backoff.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        max_timeout: float = 300.0,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._base_timeout = recovery_timeout
        self._max_timeout = max_timeout

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._current_timeout = recovery_timeout
        self._lock = asyncio.Lock()
        self._probe_in_flight = False

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def stats(self) -> dict[str, Any]:
        """Snapshot of circuit breaker metrics."""
        return {
            "name": self._name,
            "state": self._state,
            "failure_count": self._failure_count,
            "last_failure_time": self._last_failure_time,
            "current_timeout": self._current_timeout,
        }

    def reset(self) -> None:
        """Force circuit back to CLOSED (admin override)."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._current_timeout = self._base_timeout
        self._probe_in_flight = False

    async def call(self, coro: Awaitable[T]) -> T:
        """Execute an awaitable through the circuit breaker.

        Parameters
        ----------
        coro:
            An awaitable (coroutine) to execute.

        Returns
        -------
            The result of the awaitable.

        Raises
        ------
        CircuitOpenError:
            If the circuit is OPEN and cooldown has not elapsed, or if
            a probe is already in flight during HALF_OPEN.
        """
        # Decide action under lock, then execute outside lock.
        is_probe = False
        async with self._lock:
            if self._state == CircuitState.OPEN and self._cooldown_elapsed():
                self._state = CircuitState.HALF_OPEN

            if self._state == CircuitState.OPEN:
                _close_coroutine(coro)
                raise CircuitOpenError(
                    f"Circuit '{self._name}' is open — retry after {self._current_timeout:.1f}s"
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._probe_in_flight:
                    # Another call is already probing — reject this one
                    _close_coroutine(coro)
                    raise CircuitOpenError(f"Circuit '{self._name}' is half-open — probe in flight")
                self._probe_in_flight = True
                is_probe = True

        # Execute outside lock so concurrent CLOSED calls are not serialized.
        if is_probe:
            return await self._probe(coro)
        return await self._execute_closed(coro)

    def _cooldown_elapsed(self) -> bool:
        """Check whether enough time has passed since last failure."""
        if self._last_failure_time is None:
            return True
        return (time.monotonic() - self._last_failure_time) >= self._current_timeout

    async def _execute_closed(self, coro: Awaitable[T]) -> T:
        """Execute in CLOSED state — track failures, trip if threshold reached."""
        try:
            result = await coro
        except Exception:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                if self._failure_count >= self._failure_threshold:
                    self._state = CircuitState.OPEN
            raise
        else:
            async with self._lock:
                self._failure_count = 0
            return result

    async def _probe(self, coro: Awaitable[T]) -> T:
        """Execute a single probe in HALF_OPEN state."""
        try:
            result = await coro
        except Exception:
            async with self._lock:
                # Probe failed → back to OPEN with longer cooldown
                self._state = CircuitState.OPEN
                self._last_failure_time = time.monotonic()
                self._current_timeout = min(self._current_timeout * 2, self._max_timeout)
                self._probe_in_flight = False
            raise
        else:
            async with self._lock:
                # Probe succeeded → close circuit
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._current_timeout = self._base_timeout
                self._probe_in_flight = False
            return result


def _close_coroutine(coro: Awaitable[Any]) -> None:
    """Close an unawaited coroutine to avoid RuntimeWarning."""
    if asyncio.iscoroutine(coro):
        coro.close()
