"""Tests for cost aggregation dashboard."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.dashboard import router as dashboard_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(dashboard_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


class TestCostAggregationDashboard:
    def test_cost_aggregation_dashboard_exists(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/dashboard/outcomes", headers=AUTH_HEADER)
            assert resp.status_code == 200
