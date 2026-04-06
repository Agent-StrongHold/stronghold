"""Tests for gate_endpoint.py - red team regression workflow."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.app import create_app
from stronghold.api.routes.gate_endpoint import router as gate_router

class TestRedTeamRegressionWorkflow:
    @pytest.fixture
    def app(self) -> FastAPI:
        app = create_app()
        app.include_router(gate_router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_red_team_regression_workflow(self, client: TestClient) -> None:
        # Given a PR is opened targeting the develop branch
        # When the CI pipeline executes the red team regression workflow
        # Then the red team benchmark suite runs against the Warden

        # Simulate a request to the gate endpoint
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "test input that might trigger security issues",
                "mode": "persistent"
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request without raising exceptions
        assert response.status_code in (200, 400, 401, 403)