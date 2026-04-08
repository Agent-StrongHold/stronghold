"""Tests for agents status endpoint."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.status import router as status_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(status_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestAgentsStatusEndpoint:
    def test_successfully_retrieve_list_of_loaded_agents(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/agents")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "agents" in data
            assert isinstance(data["agents"], list)
            assert len(data["agents"]) > 0
            for agent in data["agents"]:
                assert "name" in agent
                assert "version" in agent
                assert "description" in agent
                assert "model" in agent
            assert "count" in data
            assert data["count"] == len(data["agents"])

    def test_retrieve_agents_when_none_loaded(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/agents")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "agents" in data
            assert isinstance(data["agents"], list)
            assert len(data["agents"]) == 0
            assert "count" in data
            assert data["count"] == 0
