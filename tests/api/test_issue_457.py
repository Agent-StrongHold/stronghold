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
            assert final_event["type"] == "done"
            assert "content" in final_event
