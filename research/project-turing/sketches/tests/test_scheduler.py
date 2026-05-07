"""Tests for specs/scheduler.md: AC-10.1, 10.2, 10.3, 10.4, 10.5, 10.9, 10.10."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from turing.motivation import ACTION_CADENCE_TICKS, BacklogItem, Motivation, PipelineState
from turing.reactor import FakeReactor
from turing.scheduler import Scheduler, ScheduledItem


def _item(
    *,
    item_id: str = "s1",
    early: datetime,
    delivery: datetime,
    duration: timedelta = timedelta(seconds=30),
    callback: str = "cb",
) -> ScheduledItem:
    return ScheduledItem(
        item_id=item_id,
        self_id="self-A",
        delivery_time=delivery,
        early_executable_start=early,
        estimated_duration=duration,
        payload={"work": "write-a-report"},
        delivery_callback_name=callback,
    )


def test_ac_10_1_item_before_window_not_in_backlog() -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    sched = Scheduler(reactor, motivation)

    future = datetime.now(UTC) + timedelta(hours=1)
    item = _item(early=future, delivery=future + timedelta(minutes=10))
    sched.schedule(item)

    reactor.tick(5)
    assert not any(b.item_id == item.item_id for b in motivation.backlog)


def test_ac_10_2_item_enters_backlog_when_window_opens() -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    sched = Scheduler(reactor, motivation)

    past = datetime.now(UTC) - timedelta(seconds=1)
    item = _item(early=past, delivery=past + timedelta(minutes=10))
    sched.schedule(item)

    reactor.tick(1)
    assert any(b.item_id == item.item_id for b in motivation.backlog)


def test_ac_10_3_idempotent_insertion() -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    sched = Scheduler(reactor, motivation)

    past = datetime.now(UTC) - timedelta(seconds=1)
    item = _item(early=past, delivery=past + timedelta(minutes=10))
    sched.schedule(item)

    reactor.tick(1)
    reactor.tick(1)
    reactor.tick(1)
    matching = [b for b in motivation.backlog if b.item_id == item.item_id]
    assert len(matching) == 1


def test_ac_10_5_output_held_until_delivery_time() -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    delivered: list[object] = []
    sched = Scheduler(
        reactor,
        motivation,
        callback_registry={"cb": delivered.append},
    )

    past = datetime.now(UTC) - timedelta(seconds=1)
    delivery = datetime.now(UTC) + timedelta(hours=1)
    item = _item(early=past, delivery=delivery, callback="cb")
    sched.schedule(item)

    # Tick until the action sweep picks it up.
    reactor.tick(ACTION_CADENCE_TICKS)

    # Output produced but not delivered yet.
    assert delivered == []


def test_ac_10_4_delivery_callback_fires_at_time() -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    delivered: list[object] = []
    sched = Scheduler(
        reactor,
        motivation,
        callback_registry={"cb": delivered.append},
    )

    past = datetime.now(UTC) - timedelta(seconds=1)
    delivery = datetime.now(UTC) - timedelta(milliseconds=100)    # already due
    item = _item(early=past, delivery=delivery, callback="cb")
    sched.schedule(item)

    reactor.tick(ACTION_CADENCE_TICKS)
    # Both sweep (produces output) and the next tick (flushes delivery).
    reactor.tick(1)

    assert len(delivered) == 1


def test_ac_10_9_and_10_10_quiet_zone_suppresses_daydream() -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    sched = Scheduler(
        reactor,
        motivation,
        avg_daydream_duration=timedelta(milliseconds=500),
    )
    soon = datetime.now(UTC) + timedelta(seconds=1)
    item = _item(early=soon, delivery=soon + timedelta(minutes=1))
    sched.schedule(item)

    zones = sched.quiet_zones()
    assert len(zones) == 1
    start, end = zones[0]
    # Zone starts 5 * 500ms = 2.5s before early-executable start.
    assert end - start == timedelta(milliseconds=2500)
    assert end == item.early_executable_start

    # State in the zone: daydream readiness must be false.
    state_in_zone = PipelineState(
        now=item.early_executable_start - timedelta(milliseconds=100),
        pressure={},
        quiet_zones=zones,
    )
    assert state_in_zone.in_any_quiet_zone() is True

    # State outside any zone: false.
    state_out_of_zone = PipelineState(
        now=item.early_executable_start - timedelta(hours=1),
        pressure={},
        quiet_zones=zones,
    )
    assert state_out_of_zone.in_any_quiet_zone() is False
