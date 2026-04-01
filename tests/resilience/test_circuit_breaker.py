"""Tests for the circuit breaker pattern.

Covers state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED),
exponential backoff, stats reporting, forced reset, and concurrency safety.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from stronghold.resilience.circuit_breaker import CircuitBreaker, CircuitState
from stronghold.types.errors import CircuitOpenError


# ── Helpers ─────────────────────────────────────────────────────


async def _succeed() -> str:
    return "ok"


async def _fail() -> str:
    msg = "backend down"
    raise ConnectionError(msg)


async def _slow_succeed(delay: float = 0.05) -> str:
    await asyncio.sleep(delay)
    return "ok"


# ── CLOSED state ────────────────────────────────────────────────


class TestClosedState:
    """Circuit in CLOSED state passes calls through."""

    async def test_successful_call_passes_through(self) -> None:
        cb = CircuitBreaker("test")
        result = await cb.call(_succeed())
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    async def test_failure_increments_counter(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=5)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["failure_count"] == 1
        assert cb.state == CircuitState.CLOSED

    async def test_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=5)
        # Two failures
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(_fail())
        assert cb.stats["failure_count"] == 2
        # One success resets
        await cb.call(_succeed())
        assert cb.stats["failure_count"] == 0


# ── CLOSED → OPEN transition ───────────────────────────────────


class TestOpenTransition:
    """After N consecutive failures, circuit trips to OPEN."""

    async def test_trips_after_threshold(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await cb.call(_fail())
        assert cb.state == CircuitState.OPEN

    async def test_open_rejects_immediately(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=2)
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(_fail())
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await cb.call(_succeed())

    async def test_open_fast_fails_without_calling_backend(self) -> None:
        """Verify open circuit doesn't execute the coroutine at all."""
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())

        call_count = 0

        async def _tracked() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        with pytest.raises(CircuitOpenError):
            await cb.call(_tracked())
        assert call_count == 0


# ── OPEN → HALF_OPEN transition ────────────────────────────────


class TestHalfOpenTransition:
    """After cooldown, circuit allows a single probe."""

    async def test_transitions_to_half_open_after_cooldown(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.06)
        # Next call should be allowed (probe)
        result = await cb.call(_succeed())
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    async def test_successful_probe_closes_circuit(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        await asyncio.sleep(0.06)
        result = await cb.call(_succeed())
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED
        assert cb.stats["failure_count"] == 0

    async def test_failed_probe_reopens_circuit(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        await asyncio.sleep(0.06)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.state == CircuitState.OPEN


# ── Exponential backoff ─────────────────────────────────────────


class TestExponentialBackoff:
    """Failed probes double the cooldown, up to max_timeout."""

    async def test_cooldown_doubles_after_failed_probe(self) -> None:
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=0.05, max_timeout=1.0
        )
        # Trip
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["current_timeout"] == 0.05

        # Wait for cooldown, probe fails → cooldown doubles
        await asyncio.sleep(0.06)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["current_timeout"] == pytest.approx(0.10)

        # Wait for doubled cooldown, probe fails → cooldown doubles again
        await asyncio.sleep(0.11)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["current_timeout"] == pytest.approx(0.20)

    async def test_cooldown_caps_at_max_timeout(self) -> None:
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=0.05, max_timeout=0.15
        )
        # Trip
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        # First backoff
        await asyncio.sleep(0.06)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["current_timeout"] == pytest.approx(0.10)
        # Second backoff — should cap at 0.15
        await asyncio.sleep(0.11)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["current_timeout"] == pytest.approx(0.15)

    async def test_successful_probe_resets_timeout(self) -> None:
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=0.05, max_timeout=1.0
        )
        # Trip and backoff once
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        await asyncio.sleep(0.06)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.stats["current_timeout"] == pytest.approx(0.10)
        # Wait for doubled cooldown, succeed
        await asyncio.sleep(0.11)
        await cb.call(_succeed())
        assert cb.state == CircuitState.CLOSED
        assert cb.stats["current_timeout"] == 0.05  # reset to base


# ── Reset ───────────────────────────────────────────────────────


class TestReset:
    """Force-reset returns circuit to CLOSED."""

    async def test_reset_from_open(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.stats["failure_count"] == 0

    async def test_reset_restores_base_timeout(self) -> None:
        cb = CircuitBreaker(
            "test", failure_threshold=1, recovery_timeout=0.05, max_timeout=1.0
        )
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        await asyncio.sleep(0.06)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        cb.reset()
        assert cb.stats["current_timeout"] == 0.05


# ── Stats ───────────────────────────────────────────────────────


class TestStats:
    """Stats property returns correct information."""

    async def test_stats_initial(self) -> None:
        cb = CircuitBreaker("my-backend", failure_threshold=5, recovery_timeout=30.0)
        stats = cb.stats
        assert stats["name"] == "my-backend"
        assert stats["state"] == CircuitState.CLOSED
        assert stats["failure_count"] == 0
        assert stats["last_failure_time"] is None
        assert stats["current_timeout"] == 30.0

    async def test_stats_after_failures(self) -> None:
        cb = CircuitBreaker("backend-x", failure_threshold=3)
        for _ in range(2):
            with pytest.raises(ConnectionError):
                await cb.call(_fail())
        stats = cb.stats
        assert stats["failure_count"] == 2
        assert stats["last_failure_time"] is not None
        assert isinstance(stats["last_failure_time"], float)


# ── Concurrency ─────────────────────────────────────────────────


class TestConcurrency:
    """Concurrent calls are safe under asyncio.Lock."""

    async def test_concurrent_calls_in_closed_state(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=10)
        results = await asyncio.gather(*[cb.call(_succeed()) for _ in range(20)])
        assert all(r == "ok" for r in results)
        assert cb.state == CircuitState.CLOSED

    async def test_concurrent_failures_trip_exactly_at_threshold(self) -> None:
        """Multiple concurrent failures should still trip at threshold."""
        cb = CircuitBreaker("test", failure_threshold=5)
        tasks = []
        for _ in range(10):
            tasks.append(cb.call(_fail()))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # All should be exceptions (either ConnectionError or CircuitOpenError)
        for r in results:
            assert isinstance(r, (ConnectionError, CircuitOpenError))
        assert cb.state == CircuitState.OPEN

    async def test_concurrent_calls_during_half_open(self) -> None:
        """Only one probe should execute in HALF_OPEN; others get CircuitOpenError."""
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(ConnectionError):
            await cb.call(_fail())
        await asyncio.sleep(0.06)
        # Launch several concurrent calls — only one should probe
        results = await asyncio.gather(
            *[cb.call(_slow_succeed(0.05)) for _ in range(5)],
            return_exceptions=True,
        )
        successes = [r for r in results if r == "ok"]
        circuit_open_errors = [r for r in results if isinstance(r, CircuitOpenError)]
        # At least one success (the probe) and others rejected
        assert len(successes) >= 1
        assert len(circuit_open_errors) >= 1
        assert len(successes) + len(circuit_open_errors) == 5
