"""Tests for agent marketplace browsing."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.marketplace import router as marketplace_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(marketplace_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


class TestBrowseAgentsEndpoint:
    def test_agents_endpoint_returns_200(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/marketplace/agents")
            assert resp.status_code == 200


class TestSearchAgentsEndpoint:
    def test_search_for_data_processing_agents(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/marketplace/agents", params={"query": "data-processing"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            # Verify at least one agent matches the search term
            agent_names = [agent.get("name", "") for agent in data]
            matching_agents = [name for name in agent_names if "data-processing" in name.lower()]
            assert len(matching_agents) > 0
