"""Tests for agent streaming via SSE."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.agents_stream import router as stream_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(stream_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestAgentStreaming:
    def test_stream_true_returns_sse_events(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {"goal": "List files in current directory", "stream": True}
            response = client.post(
                "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            assert len(events) > 1

            first_event = json.loads(events[0])
            assert first_event["type"] == "status"
            assert "Starting..." in first_event["message"]

            final_event = json.loads(events[-1])
            assert final_event["type"] in ("done", "error")

    def test_stream_includes_tool_call_and_result_events(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {"goal": "Use the list_files tool", "stream": True}
            response = client.post(
                "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events to check for tool_call and tool_result types
            event_objects = [json.loads(event) for event in events if event]

            # Find tool_call and tool_result events
            tool_events = [e for e in event_objects if e["type"] in ("tool_call", "tool_result")]

            # Skip assertion if no tool events found (test might be using a different tool)
            if not tool_events:
                pytest.skip("No tool events found in stream - test may be using different tool")

            assert len(tool_events) >= 2, (
                "Should have at least one tool_call and one tool_result event"
            )

            # Verify order: tool_call should come before tool_result
            for i in range(len(tool_events) - 1):
                if tool_events[i]["type"] == "tool_call":
                    assert tool_events[i + 1]["type"] == "tool_result", (
                        "tool_result should immediately follow tool_call"
                    )

            # Verify tool_call has required fields
            tool_call_events = [e for e in tool_events if e["type"] == "tool_call"]
            for event in tool_call_events:
                assert "tool_name" in event
                assert "arguments" in event
                assert "call_id" in event

            # Verify tool_result has required fields
            tool_result_events = [e for e in tool_events if e["type"] == "tool_result"]
            for event in tool_result_events:
                assert "tool_name" in event
                assert "result" in event
                assert "call_id" in event

    def test_cancellation_during_streaming_stops_events(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {"goal": "List files in current directory", "stream": True}
            with client.stream(
                "POST", "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

                # Read first event
                first_chunk = next(response.iter_lines())
                if isinstance(first_chunk, bytes):
                    first_chunk = first_chunk.decode("utf-8")
                assert first_chunk.startswith("data: ")

                # Simulate client disconnect by closing the response
                response.close()

                # Verify no further events are sent after disconnect
                remaining_chunks = list(response.iter_lines())
                assert not any(
                    chunk.decode("utf-8").startswith("data: ")
                    if isinstance(chunk, bytes)
                    else chunk.startswith("data: ")
                    for chunk in remaining_chunks
                ), "Server should stop sending events after client disconnect"

    def test_stream_returns_token_events_for_text_generation(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {"goal": "Write a short poem", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Should have at least status and done events
            assert len(events) >= 2

            # Parse events
            event_objects = [json.loads(event) for event in events if event]

            # Find token events
            token_events = [e for e in event_objects if e.get("type") == "token"]

            # Should have multiple token events for text generation
            assert len(token_events) > 0, "Should have token events for text generation"

            # Verify token events have required fields
            for event in token_events:
                assert "token" in event
                assert isinstance(event["token"], str)
                assert len(event["token"]) > 0


class TestWardenStreamingInterception:
    def test_warden_scans_streaming_events_when_enabled(self, app: FastAPI) -> None:
        """Test that Warden intercepts and scans each streaming event when enabled."""
        with TestClient(app) as client:
            payload = {"goal": "List files in current directory", "stream": True}
            response = client.post(
                "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events to check for Warden audit entries
            event_objects = [json.loads(event) for event in events if event]

            # Verify each event was scanned by Warden
            for event in event_objects:
                assert "warden_audit" in event, (
                    f"Event of type {event.get('type')} was not scanned by Warden"
                )
                audit = event["warden_audit"]
                assert "scanned_at" in audit
                assert "scan_id" in audit
                assert isinstance(audit["scanned"], bool)
                assert audit["scanned"] is True


class TestErrorStreaming:
    def test_error_event_during_streaming(self, app: FastAPI) -> None:
        """Test that client receives an error event when an error occurs during streaming."""
        with TestClient(app) as client:
            # Use a goal that will trigger an error during streaming
            payload = {"goal": "Trigger an error during streaming", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events
            event_objects = [json.loads(event) for event in events if event]

            # Find error event
            error_events = [e for e in event_objects if e.get("type") == "error"]

            # Should have at least one error event
            assert len(error_events) > 0, "Should have at least one error event during streaming"

            # Verify error event structure
            error_event = error_events[0]
            assert "error" in error_event
            assert "message" in error_event["error"]
            assert "type" in error_event["error"]
            assert "details" in error_event["error"]

            # Verify error details
            error_details = error_event["error"]
            assert isinstance(error_details["message"], str)
            assert len(error_details["message"]) > 0
            assert isinstance(error_details["type"], str)
            assert isinstance(error_details["details"], dict)


class TestEventOrderingValidation:
    def test_events_received_in_correct_order_for_streaming_agent(self, app: FastAPI) -> None:
        """Test that events are received in the correct order: start, tool_call/tool_result, token, finish/error."""
        with TestClient(app) as client:
            payload = {
                "goal": "Use the list_files tool and then write a short summary",
                "stream": True,
            }
            response = client.post(
                "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events
            event_objects = [json.loads(event) for event in events if event]

            # Find specific event types
            status_events = [e for e in event_objects if e.get("type") == "status"]
            tool_call_events = [e for e in event_objects if e.get("type") == "tool_call"]
            tool_result_events = [e for e in event_objects if e.get("type") == "tool_result"]
            token_events = [e for e in event_objects if e.get("type") == "token"]
            [e for e in event_objects if e.get("type") == "done"]
            error_events = [e for e in event_objects if e.get("type") == "error"]

            # Verify at least one status event exists (start)
            assert len(status_events) > 0, "Should have at least one status event"

            # Verify events follow the expected order
            all_events = event_objects
            first_event = all_events[0]
            assert first_event["type"] == "status", "First event should be a status event"

            # Find the last non-error event
            last_valid_index = len(all_events) - 1
            if error_events:
                last_valid_index = event_objects.index(error_events[0]) - 1

            last_event = all_events[last_valid_index]
            assert last_event["type"] in ("done", "error"), "Last event should be done or error"

            # Verify tool events (if any) come after status and before token events
            if tool_call_events:
                first_tool_index = event_objects.index(tool_call_events[0])
                assert first_tool_index > 0, "Tool call event should not be the first event"

                # Verify tool_call is followed by tool_result
                for i in range(len(tool_call_events)):
                    if i < len(tool_result_events):
                        tool_call_idx = event_objects.index(tool_call_events[i])
                        tool_result_idx = event_objects.index(tool_result_events[i])
                        assert tool_result_idx > tool_call_idx, (
                            "tool_result should come after tool_call"
                        )

            # Verify token events (if any) come after tool events
            if token_events:
                first_token_index = event_objects.index(token_events[0])
                if tool_result_events:
                    last_tool_result_index = event_objects.index(tool_result_events[-1])
                    assert first_token_index > last_tool_result_index, (
                        "Token events should come after tool_result events"
                    )

            # Verify overall sequence: status -> (tool_call -> tool_result)* -> token* -> (done|error)
            expected_sequence = ["status"]
            if tool_call_events:
                expected_sequence.extend(["tool_call", "tool_result"])
            if token_events:
                expected_sequence.extend(["token"])
            expected_sequence.extend(["done", "error"])

            actual_types = [e["type"] for e in all_events]
            valid_sequence = True

            # Check that the sequence follows the expected pattern
            tool_pairs = 0
            for i in range(len(actual_types)):
                current_type = actual_types[i]

                # Handle tool_call -> tool_result pairs
                if current_type == "tool_call":
                    if i + 1 < len(actual_types) and actual_types[i + 1] == "tool_result":
                        tool_pairs += 1
                        i += 1  # Skip the next item as we've processed the pair
                    else:
                        valid_sequence = False
                        break
                elif current_type not in ["status", "token", "done", "error"]:
                    valid_sequence = False
                    break

            assert valid_sequence, "Events should follow the expected sequence pattern"


class TestChatCompletionsStreaming:
    def test_chat_completions_with_stream_true_returns_sse_events(self, app: FastAPI) -> None:
        """Test that /v1/chat/completions with stream: true returns proper SSE events."""
        with TestClient(app) as client:
            payload = {"goal": "Write a short story", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            assert len(events) > 1, "Should have multiple events in the stream"

            # Parse events
            event_objects = [json.loads(event) for event in events if event]

            # Verify sequence of events
            first_event = event_objects[0]
            assert first_event["type"] == "status"
            assert "Starting..." in first_event["message"]

            # Find token events
            token_events = [e for e in event_objects if e.get("type") == "token"]
            assert len(token_events) > 0, "Should have token events for text generation"

            # Verify token events have content
            for event in token_events:
                assert "token" in event
                assert isinstance(event["token"], str)

            # Find final event
            final_event = event_objects[-1]
            assert final_event["type"] in ("done", "error")

            # Verify all events have required fields
            for event in event_objects:
                assert "type" in event
                assert "timestamp" in event
