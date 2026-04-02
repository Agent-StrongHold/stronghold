from __future__ import annotations

from stronghold.builders.contracts import StageEvent


def test_stage_event_records_actor_and_message() -> None:
    event = StageEvent(
        run_id="run-1",
        stage="queued",
        event="run_created",
        actor="system",
        message="created",
    )

    assert event.actor == "system"
    assert event.message == "created"
