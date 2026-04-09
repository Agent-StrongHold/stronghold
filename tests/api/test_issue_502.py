"""Tests for agent creation."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.agents import router as agents_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(agents_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestCreateAgent:
    def test_create_agent_with_required_fields(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Code Review Assistant"
            assert data["description"] == "AI-powered code reviewer"
            assert data["strategy"] == "review"
            assert data["tools"] == ["pylint", "flake8"]
            assert data["trust_tier"] == "high"
            assert data["install_count"] == 0


class TestSearchAgentsByCapability:
    def test_search_agents_by_capability_code_review(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different capabilities
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "capabilities": ["code_review", "linting"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "capabilities": ["documentation"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "capabilities": ["code_review"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)

            # Search for agents with code_review capability
            resp = client.get(
                "/v1/stronghold/agents", params={"capability": "code_review"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with code_review capability are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Code Review Assistant" in agent_names
            assert "Code Review Expert" in agent_names
            assert "Documentation Writer" not in agent_names
