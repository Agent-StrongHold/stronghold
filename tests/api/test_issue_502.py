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
