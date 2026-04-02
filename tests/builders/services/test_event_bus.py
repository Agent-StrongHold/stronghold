from __future__ import annotations

from stronghold.builders import InMemoryEventBus
from stronghold.builders.contracts import StageEvent


def test_event_bus_emits_and_filters_run_events() -> None:
    bus = InMemoryEventBus()

    event_one = StageEvent(
        run_id="run-1",
        stage="queued",
        event="run_created",
        actor="system",
        message="created",
    )
    event_two = StageEvent(
        run_id="run-2",
        stage="queued",
        event="run_created",
        actor="system",
        message="created",
    )

    bus.emit(event_one)
    bus.emit(event_two)

    assert bus.list_events(run_id="run-1") == [event_one]
    assert bus.list_events(run_id="run-2") == [event_two]
    assert bus.list_events() == [event_one, event_two]
