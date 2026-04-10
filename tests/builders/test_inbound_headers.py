"""Tests for inbound identity header acceptance on POST /runs.

Verifies intent_mode, x-session-id, traceparent, x-request-id are parsed
from headers/body and stored on RunState via the orchestrator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.builders import router as builders_router
from stronghold.builders import BuildersOrchestrator
from stronghold.api.routes.builders import _orchestrator, configure_builders_router
from tests.fakes import make_test_container

if TYPE_CHECKING:
    pass

AUTH = {"Authorization": "Bearer sk-test"}
BASE_BODY = {"repo_url": "https://github.com/owner/repo", "issue_number": 1}


def _setup() -> tuple[TestClient, BuildersOrchestrator]:
    """Create a test app with builders routes and return (client, orchestrator)."""
    app = FastAPI()
    app.include_router(builders_router)
    container = make_test_container()
    app.state.container = container
    orch = BuildersOrchestrator()
    configure_builders_router(orch)
    return TestClient(app), orch


class TestIntentMode:
    def test_from_body(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs",
                     json={**BASE_BODY, "intent_mode": "custom_mode"}, headers=AUTH)
        run = list(orch._runs.values())[-1]
        assert run.intent_mode == "custom_mode"

    def test_from_header_when_no_body(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs",
                     json=BASE_BODY, headers={**AUTH, "x-intent-mode": "from_header"})
        run = list(orch._runs.values())[-1]
        assert run.intent_mode == "from_header"

    def test_body_wins_over_header(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs",
                     json={**BASE_BODY, "intent_mode": "body_wins"},
                     headers={**AUTH, "x-intent-mode": "header_loses"})
        run = list(orch._runs.values())[-1]
        assert run.intent_mode == "body_wins"

    def test_default_when_neither(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs", json=BASE_BODY, headers=AUTH)
        run = list(orch._runs.values())[-1]
        assert run.intent_mode == "autonomous_build"


class TestSessionId:
    def test_from_header(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs",
                     json=BASE_BODY, headers={**AUTH, "x-session-id": "sess-abc"})
        run = list(orch._runs.values())[-1]
        assert run.session_id == "sess-abc"

    def test_default_empty(self) -> None:
        """Synthesis to run_id happens in the workflow, not at route time."""
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs", json=BASE_BODY, headers=AUTH)
        run = list(orch._runs.values())[-1]
        assert run.session_id == ""


class TestTraceparent:
    def test_valid_parsed(self) -> None:
        client, orch = _setup()
        tp = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"
        client.post("/v1/stronghold/builders/runs",
                     json=BASE_BODY, headers={**AUTH, "traceparent": tp})
        run = list(orch._runs.values())[-1]
        assert run.parent_trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_malformed_silently_ignored(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs",
                     json=BASE_BODY, headers={**AUTH, "traceparent": "bad-value"})
        run = list(orch._runs.values())[-1]
        assert run.parent_trace_id == ""

    def test_absent_default_empty(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs", json=BASE_BODY, headers=AUTH)
        run = list(orch._runs.values())[-1]
        assert run.parent_trace_id == ""


class TestRequestId:
    def test_from_header(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs",
                     json=BASE_BODY, headers={**AUTH, "x-request-id": "req-123"})
        run = list(orch._runs.values())[-1]
        assert run.request_id == "req-123"

    def test_generated_when_absent(self) -> None:
        client, orch = _setup()
        client.post("/v1/stronghold/builders/runs", json=BASE_BODY, headers=AUTH)
        run = list(orch._runs.values())[-1]
        assert len(run.request_id) == 32  # uuid hex
