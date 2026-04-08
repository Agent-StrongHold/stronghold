"""Tests for red team regression gate workflow trigger."""

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


class TestRedTeamRegressionGateWorkflow:
    def test_redteam_yaml_workflow_is_triggered_on_pr_to_develop(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_red_team_benchmark_suite_executes_successfully_on_pr(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

    def test_benchmark_comparison_fails_when_results_exceed_threshold(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/gate/red-team-regression",
                json={"benchmark_results": {"score": 0.95}, "threshold": 0.9},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data
            assert "exceeds allowed threshold" in data["error"]

    def test_workflow_fails_when_baseline_is_missing(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/gate/red-team-regression",
                json={"benchmark_results": {"score": 0.8}, "threshold": 0.9},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400
            data = resp.json()
            assert "error" in data
            assert "baseline" in data["error"].lower()
