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

    def test_returns_team_weekly_cost_breakdown(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/outcomes",
                headers=AUTH_HEADER,
                params={"group_by": "team", "period": "weekly"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "teams" in data
            assert len(data["teams"]) > 0
            assert all("team_id" in team and "costs" in team for team in data["teams"])

    def test_response_includes_model_provider_task_type_breakdown(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/outcomes",
                headers=AUTH_HEADER,
                params={"group_by": "team", "period": "weekly"},
            )
            data = resp.json()
            for team in data["teams"]:
                costs = team["costs"]
                assert "by_model" in costs
                assert "by_provider" in costs
                assert "by_task_type" in costs
                assert all(
                    isinstance(item, dict) and "cost" in item and "count" in item
                    for category in [costs["by_model"], costs["by_provider"], costs["by_task_type"]]
                    for item in category
                )

    def test_response_includes_cost_trend_data(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/outcomes",
                headers=AUTH_HEADER,
                params={"group_by": "team", "period": "weekly"},
            )
            data = resp.json()
            for team in data["teams"]:
                costs = team["costs"]
                assert "trends" in costs
                assert "daily" in costs["trends"]
                assert "weekly" in costs["trends"]
                assert all(
                    isinstance(day, dict) and "date" in day and "cost" in day
                    for day in costs["trends"]["daily"]
                )
                assert all(
                    isinstance(week, dict) and "week" in week and "cost" in week
                    for week in costs["trends"]["weekly"]
                )

    def test_export_team_costs_as_csv(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get(
                "/dashboard/outcomes",
                headers=AUTH_HEADER,
                params={"group_by": "team", "period": "weekly", "format": "csv"},
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "text/csv; charset=utf-8"
            assert "team_id" in resp.text
            assert "user" in resp.text
            assert "model" in resp.text
            assert "provider" in resp.text
            assert "task_type" in resp.text
            assert "cost" in resp.text
