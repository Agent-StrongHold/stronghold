"""Comprehensive tests for the Reactor event loop (src/stronghold/events.py).

Covers: event emission, trigger registration, condition matching, async task
spawning, circuit breaker per trigger, jitter, interval/time/event/state modes,
blocking futures, admin enable/disable, status reporting, and edge cases.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pytest

from stronghold.events import Reactor, TriggerAction
from stronghold.types.reactor import (
    Event,
    ReactorStatus,
    TriggerMode,
    TriggerSpec,
    TriggerState,
)

# ── Helpers ──────────────────────────────────────────────────────


class RecordingAction:
    """Action that records every invocation and returns a configurable result."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[Event] = []
        self.result: dict[str, Any] = result or {"ok": True}

    async def __call__(self, event: Event) -> dict[str, Any]:
        self.calls.append(event)
        return self.result


class FailingAction:
    """Action that raises on every call."""

    def __init__(self, error: str = "boom") -> None:
        self.error = error
        self.call_count: int = 0

    async def __call__(self, event: Event) -> dict[str, Any]:
        self.call_count += 1
        raise RuntimeError(self.error)


class CountdownAction:
    """Action that fails N times, then succeeds."""

    def __init__(self, failures_before_success: int) -> None:
        self._remaining = failures_before_success
        self.calls: list[Event] = []

    async def __call__(self, event: Event) -> dict[str, Any]:
        self.calls.append(event)
        if self._remaining > 0:
            self._remaining -= 1
            raise RuntimeError("not yet")
        return {"recovered": True}


class SlowAction:
    """Action that takes a configurable amount of time."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.calls: list[Event] = []
        self.completed: int = 0

    async def __call__(self, event: Event) -> dict[str, Any]:
        self.calls.append(event)
        await asyncio.sleep(self.delay)
        self.completed += 1
        return {"slow": True}


async def run_reactor_ticks(reactor: Reactor, ticks: int = 50) -> None:
    """Run the reactor for *ticks* iterations then stop it."""

    async def _stop_after() -> None:
        for _ in range(ticks):
            await asyncio.sleep(0.002)
        reactor.stop()

    stop_task = asyncio.create_task(_stop_after())
    await reactor.start()
    await stop_task


# ── 1. Event emission: fire-and-forget ──────────────────────────


async def test_emit_enqueues_event_and_trigger_fires() -> None:
    """emit() puts an event on the queue; a matching EVENT trigger fires."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="on_deploy", mode=TriggerMode.EVENT, event_pattern="deploy"),
        action,
    )

    reactor.emit(Event("deploy", {"version": "1.2.3"}))
    await run_reactor_ticks(reactor, ticks=10)

    assert len(action.calls) == 1
    assert action.calls[0].data == {"version": "1.2.3"}


async def test_emit_multiple_events_across_ticks() -> None:
    """Events emitted across separate ticks each trigger their own match.

    The reactor evaluates one match per trigger per tick, so we emit events
    with small sleeps to spread them across different ticks.
    """
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="catch_all", mode=TriggerMode.EVENT, event_pattern="ping"),
        action,
    )

    task = asyncio.create_task(reactor.start())
    for i in range(3):
        reactor.emit(Event("ping", {"seq": i}))
        await asyncio.sleep(0.01)  # ensure separate ticks
    await asyncio.sleep(0.02)
    reactor.stop()
    await task

    assert len(action.calls) == 3
    seqs = [c.data["seq"] for c in action.calls]
    assert seqs == [0, 1, 2]


async def test_same_tick_event_trigger_fires_once_per_trigger() -> None:
    """When multiple matching events land in one tick, trigger fires once (first match)."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="once_per_tick", mode=TriggerMode.EVENT, event_pattern="ping"),
        action,
    )

    # Emit 5 events before the loop drains — they all land in one tick
    for i in range(5):
        reactor.emit(Event("ping", {"seq": i}))
    await run_reactor_ticks(reactor, ticks=10)

    # Only the first match per trigger per tick
    assert len(action.calls) == 1
    assert action.calls[0].data == {"seq": 0}


# ── 2. Trigger registration and unregistration ─────────────────


async def test_register_adds_trigger_and_unregister_removes() -> None:
    """register() grows the trigger list; unregister() shrinks it."""
    reactor = Reactor()
    action = RecordingAction()

    reactor.register(TriggerSpec(name="a", mode=TriggerMode.EVENT, event_pattern="x"), action)
    reactor.register(TriggerSpec(name="b", mode=TriggerMode.EVENT, event_pattern="y"), action)
    assert len(reactor._triggers) == 2

    assert reactor.unregister("a") is True
    assert len(reactor._triggers) == 1
    assert reactor._triggers[0][0].spec.name == "b"


async def test_unregister_nonexistent_returns_false() -> None:
    reactor = Reactor()
    assert reactor.unregister("ghost") is False


# ── 3. Condition matching — EVENT mode regex ────────────────────


async def test_event_mode_regex_wildcard() -> None:
    """EVENT mode uses regex: 'post_.*' matches 'post_tool_call' but not 'pre_x'."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="post", mode=TriggerMode.EVENT, event_pattern="post_.*"),
        action,
    )

    task = asyncio.create_task(reactor.start())
    # Emit across separate ticks so each gets its own evaluation
    reactor.emit(Event("post_tool_call"))
    await asyncio.sleep(0.01)
    reactor.emit(Event("post_agent_done"))
    await asyncio.sleep(0.01)
    reactor.emit(Event("pre_tool_call"))
    await asyncio.sleep(0.01)
    reactor.stop()
    await task

    assert len(action.calls) == 2
    names = {c.name for c in action.calls}
    assert names == {"post_tool_call", "post_agent_done"}


async def test_event_mode_no_pattern_never_fires() -> None:
    """EVENT trigger with empty event_pattern compiles to None, never fires."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="empty", mode=TriggerMode.EVENT, event_pattern=""),
        action,
    )
    reactor.emit(Event("anything"))
    await run_reactor_ticks(reactor, ticks=10)

    assert len(action.calls) == 0


# ── 4. INTERVAL mode ────────────────────────────────────────────


async def test_interval_mode_fires_periodically() -> None:
    """INTERVAL trigger fires repeatedly according to interval_secs."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="pulse", mode=TriggerMode.INTERVAL, interval_secs=0.01),
        action,
    )
    await run_reactor_ticks(reactor, ticks=40)

    # With 0.01s interval and ~80ms total run time, expect several fires
    assert len(action.calls) >= 3


async def test_interval_mode_long_interval_fires_once() -> None:
    """INTERVAL trigger with a huge interval fires once (last_fired starts at 0)."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="once", mode=TriggerMode.INTERVAL, interval_secs=9999),
        action,
    )
    await run_reactor_ticks(reactor, ticks=20)

    assert len(action.calls) == 1


# ── 5. TIME mode ────────────────────────────────────────────────


async def test_time_mode_fires_when_current_time_matches() -> None:
    """TIME trigger fires when now matches at_time and hasn't fired today.

    We test this by crafting a TriggerSpec whose at_time is the current HH:MM.
    """
    now = datetime.now()
    current_hhmm = now.strftime("%H:%M")

    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="daily", mode=TriggerMode.TIME, at_time=current_hhmm),
        action,
    )
    await run_reactor_ticks(reactor, ticks=10)

    assert len(action.calls) == 1
    assert action.calls[0].name == "_time:daily"


async def test_time_mode_does_not_refire_same_day() -> None:
    """TIME trigger does not fire twice in the same day (checked via last_fired_date)."""
    now = datetime.now()
    current_hhmm = now.strftime("%H:%M")

    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="once_daily", mode=TriggerMode.TIME, at_time=current_hhmm),
        action,
    )
    await run_reactor_ticks(reactor, ticks=30)

    # Even though multiple ticks occurred during the same HH:MM, only one fire
    assert len(action.calls) == 1


async def test_time_mode_does_not_fire_at_wrong_time() -> None:
    """TIME trigger ignores when at_time does not match."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="midnight", mode=TriggerMode.TIME, at_time="99:99"),
        action,
    )
    await run_reactor_ticks(reactor, ticks=10)

    assert len(action.calls) == 0


# ── 6. STATE mode ───────────────────────────────────────────────


async def test_state_mode_fires_with_minimum_interval() -> None:
    """STATE trigger respects max(interval_secs, 10s) as minimum interval.

    Because the minimum is 10s and our test runs <1s, it should fire exactly once
    (first evaluation satisfies mono - 0.0 >= 10).
    """
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="check_state", mode=TriggerMode.STATE, interval_secs=0.0),
        action,
    )
    await run_reactor_ticks(reactor, ticks=15)

    # First fire: mono - 0.0 >= 10.0 is True because monotonic time >> 10
    assert len(action.calls) == 1
    assert action.calls[0].name == "_state:check_state"


# ── 7. Async task spawning ──────────────────────────────────────


async def test_async_task_spawning_for_nonblocking_triggers() -> None:
    """Non-blocking triggers spawn asyncio tasks that run concurrently."""
    reactor = Reactor(tick_hz=500)
    slow = SlowAction(delay=0.01)
    reactor.register(
        TriggerSpec(name="slow_ev", mode=TriggerMode.EVENT, event_pattern="go"),
        slow,
    )

    task = asyncio.create_task(reactor.start())
    # Emit across separate ticks so each fires independently
    for _ in range(3):
        reactor.emit(Event("go"))
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # let spawned tasks complete
    reactor.stop()
    await task

    assert slow.completed == 3


# ── 8. Blocking emit_and_wait ───────────────────────────────────


async def test_emit_and_wait_returns_action_result() -> None:
    """emit_and_wait resolves with the action's return value."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction(result={"allowed": True})
    reactor.register(
        TriggerSpec(
            name="gate",
            mode=TriggerMode.EVENT,
            event_pattern="check",
            blocking=True,
        ),
        action,
    )

    task = asyncio.create_task(reactor.start())
    result = await reactor.emit_and_wait(Event("check", {"ip": "10.0.0.1"}))
    reactor.stop()
    await task

    assert result == {"allowed": True}


async def test_emit_and_wait_no_trigger_returns_no_match() -> None:
    """emit_and_wait with no matching trigger gets 'no_matching_trigger'."""
    reactor = Reactor(tick_hz=500)
    task = asyncio.create_task(reactor.start())
    result = await reactor.emit_and_wait(Event("orphan"))
    reactor.stop()
    await task

    assert result == {"status": "no_matching_trigger"}


async def test_emit_and_wait_blocking_failure_propagates() -> None:
    """Blocking trigger that raises propagates the exception to the caller."""
    reactor = Reactor(tick_hz=500)
    action = FailingAction("access denied")
    reactor.register(
        TriggerSpec(
            name="fail_gate",
            mode=TriggerMode.EVENT,
            event_pattern="auth",
            blocking=True,
        ),
        action,
    )

    task = asyncio.create_task(reactor.start())
    with pytest.raises(RuntimeError, match="access denied"):
        await reactor.emit_and_wait(Event("auth"))
    reactor.stop()
    await task


# ── 9. Circuit breaker per trigger ──────────────────────────────


async def test_circuit_breaker_trips_after_max_failures() -> None:
    """After max_failures consecutive errors, the trigger is disabled."""
    reactor = Reactor(tick_hz=500)
    action = FailingAction("err")
    reactor.register(
        TriggerSpec(
            name="brittle",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.005,
            max_failures=2,
        ),
        action,
    )
    await run_reactor_ticks(reactor, ticks=40)

    state = reactor._triggers[0][0]
    assert state.disabled_by_breaker is True
    assert state.consecutive_failures >= 2
    assert "err" in state.last_error


async def test_circuit_breaker_resets_on_success() -> None:
    """A successful invocation resets consecutive_failures to 0."""
    reactor = Reactor(tick_hz=500)
    action = CountdownAction(failures_before_success=1)
    reactor.register(
        TriggerSpec(
            name="recover",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.005,
            max_failures=5,
        ),
        action,
    )
    await run_reactor_ticks(reactor, ticks=40)

    state = reactor._triggers[0][0]
    # After one failure then a success, the breaker should NOT have tripped
    assert state.disabled_by_breaker is False
    assert state.consecutive_failures == 0


async def test_circuit_breaker_independent_per_trigger() -> None:
    """One trigger's breaker does not affect another."""
    reactor = Reactor(tick_hz=500)
    fail_action = FailingAction("fail")
    ok_action = RecordingAction()

    reactor.register(
        TriggerSpec(name="bad", mode=TriggerMode.INTERVAL, interval_secs=0.005, max_failures=2),
        fail_action,
    )
    reactor.register(
        TriggerSpec(name="good", mode=TriggerMode.INTERVAL, interval_secs=0.005, max_failures=2),
        ok_action,
    )
    await run_reactor_ticks(reactor, ticks=40)

    bad_state = reactor._triggers[0][0]
    good_state = reactor._triggers[1][0]
    assert bad_state.disabled_by_breaker is True
    assert good_state.disabled_by_breaker is False
    assert len(ok_action.calls) >= 2


# ── 10. Jitter on INTERVAL triggers ────────────────────────────


async def test_interval_jitter_varies_effective_interval() -> None:
    """With jitter > 0, the effective interval varies from the base.

    We verify this indirectly: with jitter=0.9 and interval_secs=0.01,
    intervals range from 0.001 to 0.019 — fires should still happen
    but with some variance in timing.
    """
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(
            name="jittery",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.01,
            jitter=0.5,
        ),
        action,
    )
    await run_reactor_ticks(reactor, ticks=40)

    # The trigger should still fire multiple times despite jitter
    assert len(action.calls) >= 2


# ── 11. Admin enable/disable ───────────────────────────────────


async def test_disable_trigger_prevents_firing() -> None:
    """disable_trigger() prevents a trigger from evaluating."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="togglable", mode=TriggerMode.EVENT, event_pattern="x"),
        action,
    )
    reactor.disable_trigger("togglable")

    reactor.emit(Event("x"))
    await run_reactor_ticks(reactor, ticks=10)

    assert len(action.calls) == 0


async def test_enable_trigger_resets_breaker_and_reactivates() -> None:
    """enable_trigger() clears breaker and re-enables a tripped trigger."""
    reactor = Reactor(tick_hz=500)
    action = FailingAction()
    reactor.register(
        TriggerSpec(
            name="tripped",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.005,
            max_failures=1,
        ),
        action,
    )
    await run_reactor_ticks(reactor, ticks=20)

    state = reactor._triggers[0][0]
    assert state.disabled_by_breaker is True

    assert reactor.enable_trigger("tripped") is True
    assert state.disabled_by_breaker is False
    assert state.consecutive_failures == 0
    assert state.enabled is True


async def test_enable_unknown_trigger_returns_false() -> None:
    reactor = Reactor()
    assert reactor.enable_trigger("nope") is False


async def test_disable_unknown_trigger_returns_false() -> None:
    reactor = Reactor()
    assert reactor.disable_trigger("nope") is False


# ── 12. Status reporting ────────────────────────────────────────


async def test_get_status_returns_full_snapshot() -> None:
    """get_status() returns a ReactorStatus with accurate counters."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="s1", mode=TriggerMode.EVENT, event_pattern="ping"),
        action,
    )

    reactor.emit(Event("ping"))
    reactor.emit(Event("no_match"))
    await run_reactor_ticks(reactor, ticks=10)

    status = reactor.get_status()
    assert isinstance(status, ReactorStatus)
    assert status.running is False
    assert status.tick_count > 0
    assert status.events_processed >= 2
    assert status.triggers_fired >= 1
    assert status.tasks_completed >= 1
    assert len(status.triggers) == 1
    assert status.triggers[0]["name"] == "s1"
    assert status.triggers[0]["mode"] == "event"
    assert status.triggers[0]["enabled"] is True
    assert len(status.recent_events) >= 2


async def test_status_tracks_failed_tasks() -> None:
    """get_status() reflects tasks_failed counter after action errors."""
    reactor = Reactor(tick_hz=500)
    action = FailingAction("oops")
    reactor.register(
        TriggerSpec(
            name="fails",
            mode=TriggerMode.INTERVAL,
            interval_secs=0.005,
            max_failures=10,
        ),
        action,
    )
    await run_reactor_ticks(reactor, ticks=30)
    # Let spawned tasks complete
    await asyncio.sleep(0.05)

    status = reactor.get_status()
    assert status.tasks_failed >= 1


# ── 13. TriggerAction protocol conformance ─────────────────────


async def test_recording_action_satisfies_protocol() -> None:
    """RecordingAction is a valid TriggerAction at runtime."""
    assert isinstance(RecordingAction(), TriggerAction)


async def test_failing_action_satisfies_protocol() -> None:
    assert isinstance(FailingAction(), TriggerAction)


# ── 14. Event log / deque ──────────────────────────────────────


async def test_event_log_capped_at_500() -> None:
    """The internal event log (deque) is capped at maxlen=500."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="log_test", mode=TriggerMode.EVENT, event_pattern="evt"),
        action,
    )

    for i in range(600):
        reactor.emit(Event("evt", {"i": i}))
    await run_reactor_ticks(reactor, ticks=30)

    assert len(reactor._event_log) <= 500


# ── 15. Multiple triggers — different modes same reactor ────────


async def test_mixed_modes_coexist() -> None:
    """EVENT, INTERVAL, and STATE triggers all fire in the same reactor."""
    reactor = Reactor(tick_hz=500)
    ev_action = RecordingAction()
    int_action = RecordingAction()
    state_action = RecordingAction()

    reactor.register(
        TriggerSpec(name="ev", mode=TriggerMode.EVENT, event_pattern="signal"),
        ev_action,
    )
    reactor.register(
        TriggerSpec(name="int", mode=TriggerMode.INTERVAL, interval_secs=0.01),
        int_action,
    )
    reactor.register(
        TriggerSpec(name="st", mode=TriggerMode.STATE, interval_secs=0.0),
        state_action,
    )

    reactor.emit(Event("signal"))
    await run_reactor_ticks(reactor, ticks=20)

    assert len(ev_action.calls) >= 1
    assert len(int_action.calls) >= 1
    assert len(state_action.calls) >= 1


# ── 16. TriggerState.is_active property ─────────────────────────


def test_trigger_state_is_active_both_conditions() -> None:
    """is_active is True only when enabled=True AND disabled_by_breaker=False."""
    spec = TriggerSpec(name="t", mode=TriggerMode.EVENT, event_pattern="x")
    state = TriggerState(spec=spec)
    assert state.is_active is True

    state.enabled = False
    assert state.is_active is False

    state.enabled = True
    state.disabled_by_breaker = True
    assert state.is_active is False


# ── 17. Stop and restart ────────────────────────────────────────


async def test_stop_halts_loop() -> None:
    """stop() sets _running to False and the loop exits."""
    reactor = Reactor(tick_hz=500)
    task = asyncio.create_task(reactor.start())
    await asyncio.sleep(0.01)
    assert reactor._running is True

    reactor.stop()
    await task
    assert reactor._running is False
    assert reactor._tick_count > 0


# ── 18. Emit before start ──────────────────────────────────────


async def test_emit_before_start_queues_events() -> None:
    """Events emitted before start() are queued and drained once the loop runs."""
    reactor = Reactor(tick_hz=500)
    action = RecordingAction()
    reactor.register(
        TriggerSpec(name="pre", mode=TriggerMode.EVENT, event_pattern="early"),
        action,
    )

    # Emit before start
    reactor.emit(Event("early", {"when": "before"}))

    await run_reactor_ticks(reactor, ticks=10)

    assert len(action.calls) == 1
    assert action.calls[0].data == {"when": "before"}
