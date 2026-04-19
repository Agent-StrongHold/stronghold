"""Tests for turing/runtime/reactor.py — RealReactor behavior.

Smoke-level tests of the blocking-tick loop. Uses low tick rates for speed.
"""

from __future__ import annotations

import threading
import time

import pytest

from turing.runtime.reactor import RealReactor


def test_tick_count_increases() -> None:
    reactor = RealReactor(tick_rate_hz=100)
    ticks_observed: list[int] = []

    def handler(tick: int) -> None:
        ticks_observed.append(tick)
        if tick >= 10:
            reactor.stop()

    reactor.register(handler)
    reactor.run_forever()

    assert ticks_observed == list(range(1, 11))


def test_tick_rate_is_honored_within_tolerance() -> None:
    reactor = RealReactor(tick_rate_hz=100)
    start = time.monotonic()

    def handler(tick: int) -> None:
        if tick >= 50:
            reactor.stop()

    reactor.register(handler)
    reactor.run_forever()
    elapsed = time.monotonic() - start

    # 50 ticks at 100Hz = ~0.5s. Allow generous tolerance.
    assert 0.35 < elapsed < 1.0, f"elapsed {elapsed:.3f}s outside tolerance"


def test_spawn_returns_future_with_result() -> None:
    reactor = RealReactor(tick_rate_hz=100)
    result_holder: dict[str, int] = {}

    def handler(tick: int) -> None:
        if tick == 1:
            future = reactor.spawn(lambda x: x * 2, 21)
            result_holder["value"] = future.result(timeout=1)
        if tick >= 2:
            reactor.stop()

    reactor.register(handler)
    reactor.run_forever()
    assert result_holder["value"] == 42


def test_spawn_captures_exceptions() -> None:
    reactor = RealReactor(tick_rate_hz=100)
    captured: dict[str, BaseException] = {}

    def handler(tick: int) -> None:
        if tick == 1:

            def _boom() -> None:
                raise ValueError("boom")

            future = reactor.spawn(_boom)
            try:
                future.result(timeout=1)
            except Exception as exc:
                captured["exc"] = exc
        if tick >= 2:
            reactor.stop()

    reactor.register(handler)
    reactor.run_forever()
    assert isinstance(captured["exc"], ValueError)


def test_handler_exceptions_do_not_stop_loop() -> None:
    reactor = RealReactor(tick_rate_hz=100)
    tick_counts: list[int] = []

    def bad_handler(tick: int) -> None:
        if tick == 2:
            raise RuntimeError("intentional")

    def good_handler(tick: int) -> None:
        tick_counts.append(tick)
        if tick >= 5:
            reactor.stop()

    reactor.register(bad_handler)
    reactor.register(good_handler)
    reactor.run_forever()
    assert tick_counts == [1, 2, 3, 4, 5]


def test_stop_is_idempotent() -> None:
    reactor = RealReactor(tick_rate_hz=100)
    reactor.stop()
    reactor.stop()  # should not raise
    reactor.register(lambda tick: None)
    reactor.run_forever()  # exits immediately
    status = reactor.get_status()
    assert status.running is False


def test_status_snapshot() -> None:
    reactor = RealReactor(tick_rate_hz=50)

    def handler(tick: int) -> None:
        if tick >= 3:
            reactor.stop()

    reactor.register(handler)
    reactor.run_forever()
    status = reactor.get_status()
    assert status.tick_count >= 3
    assert status.tick_rate_hz == 50
    assert status.running is False


def test_fake_reactor_spawn_is_synchronous() -> None:
    """Regression: FakeReactor.spawn must return a resolved Future."""
    from turing.reactor import FakeReactor

    reactor = FakeReactor()
    future = reactor.spawn(lambda: "ok")
    assert future.done()
    assert future.result() == "ok"
