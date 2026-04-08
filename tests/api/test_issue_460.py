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
            resp = client.get("/v1/stronghold/marketplace/agents", headers=AUTH_HEADER)
            assert resp.status_code == 200


class TestSearchAgentsEndpoint:
    def test_search_for_data_processing_agents(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/marketplace/agents",
                params={"query": "data-processing"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            # Verify at least one agent matches the search term
            agent_names = [agent.get("name", "") for agent in data]
            matching_agents = [name for name in agent_names if "data-processing" in name.lower()]
            assert len(matching_agents) > 0


class TestInstallAgentEndpoint:
    def test_install_agent_sets_trust_tier_to_t3(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            agent_id = "data-processing-agent-123"
            resp = client.post(
                "/v1/stronghold/marketplace/agents/install",
                headers=AUTH_HEADER,
                json={"agent_id": agent_id},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["trust_tier"] == "T3"

    def test_install_agent_blocks_unauthorized_publisher(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            agent_id = "unauthorized-agent-456"
            resp = client.post(
                "/v1/stronghold/marketplace/agents/install",
                headers=AUTH_HEADER,
                json={"agent_id": agent_id},
            )
            assert resp.status_code == 403
            data = resp.json()
            assert "detail" in data
            assert "error" in data["detail"]
            assert "publisher" in data["detail"]["error"].lower()

    def test_install_agent_fails_with_invalid_signature(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            agent_id = "invalid-signature-agent-789"
            resp = client.post(
                "/v1/stronghold/marketplace/agents/install",
                headers=AUTH_HEADER,
                json={"agent_id": agent_id},
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "detail" in data
            assert "signature" in data["detail"]["error"].lower()


class TestRateAgentEndpoint:
    def test_rate_installed_agent_records_rating(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            agent_id = "data-processing-agent-123"
            rating = 5
            resp = client.post(
                "/v1/stronghold/marketplace/agents/rate",
                headers=AUTH_HEADER,
                json={"agent_id": agent_id, "rating": rating},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "rating" in data
            assert data["rating"] == rating

    def test_rate_agent_displays_rating_in_browse(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            agent_id = "data-processing-agent-123"
            rating = 4
            client.post(
                "/v1/stronghold/marketplace/agents/rate",
                headers=AUTH_HEADER,
                json={"agent_id": agent_id, "rating": rating},
            )
            resp = client.get("/v1/stronghold/marketplace/agents", headers=AUTH_HEADER)
            data = resp.json()
            agent_data = next((a for a in data if a.get("id") == agent_id), None)
            assert agent_data is not None
            assert "rating" in agent_data
            assert agent_data["rating"] == rating


class TestViewAgentManifestEndpoint:
    def test_view_signed_manifest_for_installed_agent(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            agent_id = "data-processing-agent-123"
            resp = client.get(
                f"/v1/stronghold/marketplace/agents/{agent_id}/manifest",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "manifest" in data
            assert "signature" in data
            assert "agent_id" in data
            assert data["agent_id"] == agent_id

    def test_view_manifest_returns_404_for_unknown_agent(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            unknown_agent_id = "non-existent-agent-999"
            resp = client.get(
                f"/v1/stronghold/marketplace/agents/{unknown_agent_id}/manifest",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 404
            data = resp.json()
            assert "detail" in data
