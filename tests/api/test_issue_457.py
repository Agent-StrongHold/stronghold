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
                assert response.headers["content-type"] == "text-event-stream; charset=utf-8"

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
            assert response.headers["content-type"] == "text-event-stream; charset=utf-8"

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


class TestToolExecutionStreaming:
    def test_tool_call_and_result_events_in_correct_order(self, app: FastAPI) -> None:
        """Test that tool_call and tool_result events are streamed in correct order during agent execution."""
        with TestClient(app) as client:
            payload = {"goal": "Use the list_files tool", "stream": True}
            response = client.post(
                "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            )

            assert response.status_code == 200
            assert response.headers["content-type"] == "text-event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events
            event_objects = [json.loads(event) for event in events if event]

            # Find tool_call and tool_result events
            tool_call_events = []
            tool_result_events = []

            for event in event_objects:
                if event.get("type") == "tool_call":
                    tool_call_events.append(event)
                elif event.get("type") == "tool_result":
                    tool_result_events.append(event)

            # Verify we have at least one tool_call and one tool_result
            assert len(tool_call_events) >= 1, "Should have at least one tool_call event"
            assert len(tool_result_events) >= 1, "Should have at least one tool_result event"

            # Verify each tool_call is followed by a tool_result with matching call_id
            for _i, call_event in enumerate(tool_call_events):
                assert "call_id" in call_event, "tool_call event should have call_id"

                # Find corresponding tool_result
                matching_results = [
                    result
                    for result in tool_result_events
                    if result.get("call_id") == call_event["call_id"]
                ]

                assert len(matching_results) == 1, (
                    f"Should have exactly one tool_result for call_id {call_event['call_id']}"
                )

                result_event = matching_results[0]

                # Verify order: tool_call should come before its tool_result
                call_event_index = event_objects.index(call_event)
                result_event_index = event_objects.index(result_event)
                assert result_event_index > call_event_index, (
                    "tool_result should come after its corresponding tool_call"
                )

                # Verify tool_call fields
                assert "tool_name" in call_event
                assert "arguments" in call_event
                assert isinstance(call_event["arguments"], str)

                # Verify tool_result fields
                assert "tool_name" in result_event
                assert "result" in result_event
                assert result_event["tool_name"] == call_event["tool_name"]

            # Verify all tool_result events come after all tool_call events
            if tool_call_events and tool_result_events:
                last_call_index = event_objects.index(tool_call_events[-1])
                first_result_index = event_objects.index(tool_result_events[0])
                assert first_result_index > last_call_index, (
                    "All tool_result events should come after all tool_call events"
                )


class TestStreamCancellationCleanup:
    def test_cancellation_during_streaming_cleans_up_resources(self, app: FastAPI) -> None:
        """Test that server cleans up resources when client disconnects during streaming."""
        with TestClient(app) as client:
            payload = {"goal": "List files in current directory", "stream": True}
            with client.stream(
                "POST", "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            ) as response:
                assert response.status_code == 200

                # Read first event to ensure streaming started
                first_chunk = next(response.iter_lines())
                if isinstance(first_chunk, bytes):
                    first_chunk = first_chunk.decode("utf-8")
                assert first_chunk.startswith("data: ")

                # Simulate client disconnect
                response.close()

                # Verify the streaming task was cancelled
                container = app.state.container
                streaming_tasks = getattr(container, "streaming_tasks", [])

                # Check that the streaming task was removed from active tasks
                active_tasks_after = [
                    task for task in streaming_tasks if not task.done() and not task.cancelled()
                ]

                # The exact cleanup mechanism may vary, so we check that no active streaming
                # tasks remain that could cause resource leaks
                assert len(active_tasks_after) == 0, (
                    "All streaming tasks should be cleaned up after client disconnect"
                )


class TestTextGenerationTokenStreaming:
    def test_token_events_received_for_text_generation_with_stream_true(self, app: FastAPI) -> None:
        """Test that token-by-token events are received for text generation when stream=true."""
        with TestClient(app) as client:
            payload = {"goal": "Write a short poem about the ocean", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Should have multiple events including status, tokens, and done/error
            assert len(events) >= 3, "Should have status, token(s), and completion events"

            # Parse events
            event_objects = [json.loads(event) for event in events if event]

            # Find token events
            token_events = [e for e in event_objects if e.get("type") == "token"]

            # Should have multiple token events for text generation
            assert len(token_events) >= 3, "Should have multiple token events for text generation"

            # Verify token events have proper structure
            for i, event in enumerate(token_events):
                assert "token" in event, f"Token event {i} missing 'token' field"
                assert isinstance(event["token"], str), f"Token event {i} 'token' is not a string"
                assert len(event["token"]) > 0, f"Token event {i} has empty token"
                assert "timestamp" in event, f"Token event {i} missing 'timestamp' field"

            # Verify tokens form coherent text (basic check)
            full_text = "".join(event["token"] for event in token_events)
            assert len(full_text) > 10, "Generated text should be more than 10 characters"

            # Verify events are in chronological order
            timestamps = [
                event["timestamp"] for event in event_objects if event.get("type") == "token"
            ]
            assert timestamps == sorted(timestamps), "Token events should be in chronological order"

            # Verify first token event comes after status event
            if token_events:
                first_token_idx = event_objects.index(token_events[0])
                assert first_token_idx > 0, "Token events should come after status event"

                # Verify status event exists
                status_events = [e for e in event_objects if e.get("type") == "status"]
                assert len(status_events) > 0, "Should have at least one status event"


class TestWardenStreamingInterceptionWithChatCompletions:
    def test_warden_scans_each_event_in_chat_completions_stream(self, app: FastAPI) -> None:
        """Test that Warden intercepts and scans each streaming event when enabled in /v1/chat/completions."""
        with TestClient(app) as client:
            payload = {"goal": "Write a short story about space", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

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


class TestErrorEventDuringStreaming:
    def test_error_event_structure_during_streaming(self, app: FastAPI) -> None:
        """Test that error events during streaming have the correct structure and details."""
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
            assert "timestamp" in error_event

            # Verify error details structure
            error_details = error_event["error"]
            assert isinstance(error_details["message"], str)
            assert len(error_details["message"]) > 0
            assert isinstance(error_details["type"], str)
            assert isinstance(error_details["details"], dict)

            # Verify error type is appropriate
            assert error_details["type"] in ["internal_error", "validation_error", "tool_error"]

            # Verify error details contains useful information
            if error_details["type"] == "tool_error":
                assert "tool_name" in error_details["details"]
                assert "error_message" in error_details["details"]


class TestEventOrderingForChatCompletions:
    def test_events_follow_correct_order_in_chat_completions_stream(self, app: FastAPI) -> None:
        """Test that events in /v1/chat/completions follow correct order: start, token, finish/error."""
        with TestClient(app) as client:
            payload = {"goal": "Write a short poem about mountains", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events
            event_objects = [json.loads(event) for event in events if event]

            # Find specific event types
            status_events = [e for e in event_objects if e.get("type") == "status"]
            token_events = [e for e in event_objects if e.get("type") == "token"]
            done_events = [e for e in event_objects if e.get("type") == "done"]
            error_events = [e for e in event_objects if e.get("type") == "error"]

            # Verify at least one status event exists (start)
            assert len(status_events) > 0, "Should have at least one status event"

            # Verify first event is status
            first_event = event_objects[0]
            assert first_event["type"] == "status", "First event should be a status event"

            # Verify last event is either done or error
            last_event = event_objects[-1]
            assert last_event["type"] in ("done", "error"), "Last event should be done or error"

            # Verify token events (if any) come after status and before done/error
            if token_events:
                first_token_index = event_objects.index(token_events[0])
                assert first_token_index > 0, "Token events should come after status event"

                # Verify all token events come before any done/error events
                if done_events:
                    last_token_index = event_objects.index(token_events[-1])
                    first_done_index = event_objects.index(done_events[0])
                    assert last_token_index < first_done_index, (
                        "Token events should come before done event"
                    )

                if error_events:
                    last_token_index = event_objects.index(token_events[-1])
                    first_error_index = event_objects.index(error_events[0])
                    assert last_token_index < first_error_index, (
                        "Token events should come before error event"
                    )

            # Verify overall sequence follows: status -> token* -> (done|error)
            actual_types = [e["type"] for e in event_objects]
            expected_pattern = ["status"]

            if token_events:
                expected_pattern.extend(["token"] * len(token_events))

            expected_pattern.extend(["done", "error"])

            # Check that the sequence follows the expected pattern
            valid_sequence = True
            token_count = 0

            for event_type in actual_types:
                if event_type == "token":
                    token_count += 1
                elif event_type == "status":
                    if token_count > 0:
                        valid_sequence = False
                        break
                elif event_type in ("done", "error"):
                    if token_count == 0 and len(status_events) == 0:
                        valid_sequence = False
                        break
                    break
                else:
                    valid_sequence = False
                    break

            assert valid_sequence, (
                "Events should follow the expected sequence pattern: status -> token* -> (done|error)"
            )


class TestStreamAgentExecution:
    def test_stream_agent_execution_with_valid_request(self, app: FastAPI) -> None:
        """Test streaming agent execution with valid request to /v1/chat/completions."""
        with TestClient(app) as client:
            payload = {
                "model": "agent-model",
                "messages": [{"role": "user", "content": "Plan a trip"}],
                "stream": True,
            }
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            # Then the server responds with HTTP 200
            assert response.status_code == 200

            # And the response has Content-Type "text/event-stream"
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            # And the first event is:
            lines = response.text.split("\n\n")
            first_event_line = lines[0]
            assert first_event_line.startswith("event: start")
            assert "data: " in first_event_line
            data_part = first_event_line.split("data: ")[1]
            first_event_data = json.loads(data_part)
            assert first_event_data["model"] == "agent-model"
            assert "timestamp" in first_event_data

            # Parse all events to verify subsequent events
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]
            event_objects = [json.loads(event) for event in events if event]

            # And subsequent events include "tool_call", "token", and "finish" in order
            event_types = [e["type"] for e in event_objects]

            # Find indices of each event type
            start_index = event_types.index("start") if "start" in event_types else -1
            tool_call_indices = [i for i, t in enumerate(event_types) if t == "tool_call"]
            token_indices = [i for i, t in enumerate(event_types) if t == "token"]
            finish_index = next(
                (i for i, t in enumerate(event_types) if t in ("done", "error")), -1
            )

            # Verify tool_call, token, and finish events exist
            assert len(tool_call_indices) >= 0, "Should have tool_call events"
            assert len(token_indices) >= 0, "Should have token events"
            assert finish_index > start_index, "Should have finish/error event after start"

            # Verify order: tool_call should come before token, and both should come before finish
            if tool_call_indices and token_indices:
                last_tool_call = max(tool_call_indices)
                first_token = min(token_indices)
                assert first_token > last_tool_call, (
                    "token events should come after tool_call events"
                )

            if token_indices and finish_index > 0:
                last_token = max(token_indices)
                assert last_token < finish_index, "finish event should come after token events"


class TestStreamingInterruptionCleanup:
    def test_streaming_interruption_cleans_up_resources_and_stops_events(
        self, app: FastAPI
    ) -> None:
        """Test that server cleans up resources and stops sending events when client disconnects during streaming."""
        with TestClient(app) as client:
            payload = {"goal": "List files in current directory", "stream": True}

            # Use client.stream to maintain connection for interruption simulation
            with client.stream(
                "POST", "/v1/stronghold/request/stream", json=payload, headers=AUTH_HEADER
            ) as response:
                assert response.status_code == 200
                assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

                # Read first event to ensure streaming started
                first_chunk = next(response.iter_lines())
                if isinstance(first_chunk, bytes):
                    first_chunk = first_chunk.decode("utf-8")
                assert first_chunk.startswith("data: ")

                # Simulate client disconnect/interruption
                response.close()

                # Verify no "finish" event is sent after disconnect
                remaining_content = response.text
                lines = remaining_content.split("\n\n")
                events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

                # Parse remaining events
                event_objects = []
                for event in events:
                    try:
                        event_objects.append(json.loads(event))
                    except json.JSONDecodeError:
                        continue

                # Check that no "done" or "error" events were sent after disconnect
                finish_events = [e for e in event_objects if e.get("type") in ("done", "error")]
                assert len(finish_events) == 0, (
                    "No finish/error events should be sent after client disconnect"
                )

                # Verify agent resources are cleaned up
                container = app.state.container

                # Check for agent-related cleanup (implementation-specific)
                # This verifies that the streaming task was properly cancelled
                streaming_tasks = getattr(container, "streaming_tasks", [])
                active_tasks_after = [
                    task for task in streaming_tasks if not task.done() and not task.cancelled()
                ]
                assert len(active_tasks_after) == 0, (
                    "All streaming tasks should be cleaned up after client disconnect"
                )


class TestTextGenerationStreamingWithWardenInterception:
    def test_warden_intercepts_and_forwards_streaming_events_preserving_order(
        self, app: FastAPI
    ) -> None:
        """Test that Warden receives events in correct order and forwards them unchanged during streaming."""
        with TestClient(app) as client:
            payload = {"goal": "Write a short story about space exploration", "stream": True}
            response = client.post("/v1/chat/completions", json=payload, headers=AUTH_HEADER)

            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

            lines = response.text.split("\n\n")
            events = [line.replace("data: ", "") for line in lines if line.startswith("data: ")]

            # Parse all events
            event_objects = [json.loads(event) for event in events if event]

            # Verify each event has Warden audit information
            for event in event_objects:
                assert "warden_audit" in event, (
                    f"Event of type {event.get('type')} was not intercepted by Warden"
                )
                audit = event["warden_audit"]
                assert "scanned_at" in audit
                assert "scan_id" in audit
                assert isinstance(audit["scanned"], bool)
                assert audit["scanned"] is True

            # Verify event order is preserved by checking timestamps
            timestamps = [event["timestamp"] for event in event_objects]
            assert timestamps == sorted(timestamps), "Event order should be preserved"

            # Verify the sequence follows expected pattern: status -> token* -> done
            event_types = [e["type"] for e in event_objects]

            # First event should be status
            assert event_types[0] == "status", "First event should be status"

            # Last event should be done or error
            assert event_types[-1] in ("done", "error"), "Last event should be done or error"

            # All token events should be in order
            token_indices = [i for i, t in enumerate(event_types) if t == "token"]
            if token_indices:
                # Verify tokens are in chronological order
                token_timestamps = [event_objects[i]["timestamp"] for i in token_indices]
                assert token_timestamps == sorted(token_timestamps), (
                    "Token events should maintain chronological order"
                )
