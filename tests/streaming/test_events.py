"""Tests for structured SSE events for agent execution progress."""

from __future__ import annotations

import json

from stronghold.streaming.events import EventCollector, SSEEvent


class TestSSEEvent:
    """Tests for SSEEvent dataclass."""

    def test_format_produces_valid_sse_wire_format(self) -> None:
        """SSEEvent.format() must produce 'event: <type>\\ndata: <json>\\n\\n'."""
        event = SSEEvent(event="status", data={"phase": "classifying"})
        formatted = event.format()
        assert formatted.startswith("event: status\n")
        assert "data: " in formatted
        assert formatted.endswith("\n\n")
        # The data line must be valid JSON
        data_line = formatted.split("\n")[1]
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload == {"phase": "classifying"}

    def test_format_with_empty_data(self) -> None:
        """An event with empty data dict should still produce valid SSE."""
        event = SSEEvent(event="heartbeat", data={})
        formatted = event.format()
        assert "event: heartbeat\n" in formatted
        data_line = formatted.split("\n")[1]
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload == {}

    def test_format_with_nested_data(self) -> None:
        """Nested dicts in data must serialize to valid JSON."""
        event = SSEEvent(event="tool_call", data={"tool": "search", "arguments": {"q": "hello"}})
        formatted = event.format()
        data_line = formatted.split("\n")[1]
        payload = json.loads(data_line.removeprefix("data: "))
        assert payload["arguments"]["q"] == "hello"

    def test_default_data_is_empty_dict(self) -> None:
        """SSEEvent with no data kwarg should default to empty dict."""
        event = SSEEvent(event="done")
        assert event.data == {}


class TestEventCollector:
    """Tests for EventCollector."""

    async def test_emit_adds_event(self) -> None:
        """emit() should add an SSEEvent to the collector."""
        collector = EventCollector()
        await collector.emit("status", phase="classifying")
        assert len(collector.events) == 1
        assert collector.events[0].event == "status"
        assert collector.events[0].data["phase"] == "classifying"

    async def test_emit_status_creates_status_event_with_phase_and_detail(self) -> None:
        """emit_status() must create a status event with phase, detail, and timestamp."""
        collector = EventCollector()
        await collector.emit_status("routing", detail="selecting model")
        events = collector.events
        assert len(events) == 1
        assert events[0].event == "status"
        assert events[0].data["phase"] == "routing"
        assert events[0].data["detail"] == "selecting model"
        assert "timestamp" in events[0].data

    async def test_emit_tool_call_creates_tool_call_event(self) -> None:
        """emit_tool_call() must create a tool_call event."""
        collector = EventCollector()
        await collector.emit_tool_call("web_search", arguments={"query": "hello"})
        events = collector.events
        assert len(events) == 1
        assert events[0].event == "tool_call"
        assert events[0].data["tool"] == "web_search"
        assert events[0].data["arguments"] == {"query": "hello"}

    async def test_emit_tool_call_defaults_arguments_to_empty_dict(self) -> None:
        """emit_tool_call() with no arguments should default to {}."""
        collector = EventCollector()
        await collector.emit_tool_call("shell_exec")
        assert collector.events[0].data["arguments"] == {}

    async def test_emit_tool_result_creates_tool_result_event(self) -> None:
        """emit_tool_result() must create a tool_result event."""
        collector = EventCollector()
        await collector.emit_tool_result("web_search", success=True, detail="found 3 results")
        events = collector.events
        assert len(events) == 1
        assert events[0].event == "tool_result"
        assert events[0].data["tool"] == "web_search"
        assert events[0].data["success"] is True
        assert events[0].data["detail"] == "found 3 results"

    async def test_emit_done_sets_closed_flag(self) -> None:
        """emit_done() must set is_closed to True."""
        collector = EventCollector()
        assert not collector.is_closed
        await collector.emit_done(usage={"prompt_tokens": 100})
        assert collector.is_closed
        assert collector.events[0].event == "done"
        assert collector.events[0].data["usage"] == {"prompt_tokens": 100}

    async def test_emit_done_defaults_usage_to_empty_dict(self) -> None:
        """emit_done() with no usage should default to {}."""
        collector = EventCollector()
        await collector.emit_done()
        assert collector.events[0].data["usage"] == {}

    async def test_format_all_concatenates_all_events(self) -> None:
        """format_all() must concatenate all events in order."""
        collector = EventCollector()
        await collector.emit_status("classifying")
        await collector.emit_status("routing")
        await collector.emit_done()
        formatted = collector.format_all()
        # Should contain 3 events
        assert formatted.count("event: ") == 3
        # Order matters: first status, then done
        first_idx = formatted.index("event: status")
        done_idx = formatted.index("event: done")
        assert first_idx < done_idx

    async def test_events_list_is_ordered_by_insertion(self) -> None:
        """events property must return events in insertion order."""
        collector = EventCollector()
        await collector.emit("status", phase="a")
        await collector.emit("tool_call", tool="b")
        await collector.emit("tool_result", tool="c")
        await collector.emit("done")
        types = [e.event for e in collector.events]
        assert types == ["status", "tool_call", "tool_result", "done"]

    async def test_events_returns_copy(self) -> None:
        """events property must return a copy, not the internal list."""
        collector = EventCollector()
        await collector.emit("status", phase="test")
        events_copy = collector.events
        events_copy.clear()
        # Original should still have the event
        assert len(collector.events) == 1

    async def test_is_closed_property_default_false(self) -> None:
        """is_closed should be False by default."""
        collector = EventCollector()
        assert collector.is_closed is False

    async def test_close_sets_closed_without_emitting(self) -> None:
        """close() should set closed flag without adding events."""
        collector = EventCollector()
        await collector.emit("status", phase="working")
        collector.close()
        assert collector.is_closed
        assert len(collector.events) == 1  # only the status event
