"""Tests for uptime endpoint."""

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
    app.include_router(status_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app

class TestUptimeEndpoint:
    def test_get_uptime_success(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)
            assert "uptime_seconds" in data
            assert "started_at" in data
            assert "service" in data
            assert data["service"] == "stronghold"
            assert isinstance(data["uptime_seconds"], (int, float))
            assert data["uptime_seconds"] > 0
            assert isinstance(data["started_at"], str)

    def test_uptime_response_has_valid_iso_timestamp(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/status/uptime")
            data = resp.json()
            from datetime import datetime
            try:
                datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
            except ValueError:
                pytest.fail("started_at is not a valid ISO 8601 timestamp")

    def test_uptime_increases_over_time(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            first_resp = client.get("/v1/stronghold/status/uptime")
            assert first_resp.status_code == 200
            first_data = first_resp.json()
            assert "uptime_seconds" in first_data

            import time
            time.sleep(1)

            second_resp = client.get("/v1/stronghold/status/uptime")
            assert second_resp.status_code == 200
            second_data = second_resp.json()
            assert "uptime_seconds" in second_data

            assert second_data["uptime_seconds"] > first_data["uptime_seconds"]

    def test_uptime_increases_by_at_least_one_second(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            first_resp = client.get("/v1/stronghold/status/uptime")
            assert first_resp.status_code == 200
            first_data = first_resp.json()
            assert "uptime_seconds" in first_data

            import time
            time.sleep(1.1)

            second_resp = client.get("/v1/stronghold/status/uptime")
            assert second_resp.status_code == 200
            second_data = second_resp.json()
            assert "uptime_seconds" in second_data

            assert second_data["uptime_seconds"] >= first_data["uptime_seconds"] + 1

    def test_started_at_timestamp_consistency_across_requests(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            first_resp = client.get("/v1/stronghold/status/uptime")
            assert first_resp.status_code == 200
            first_data = first_resp.json()
            assert "started_at" in first_data

            # Make multiple requests to verify consistency
            for _ in range(5):
                resp = client.get("/v1/stronghold/status/uptime")
                assert resp.status_code == 200
                data = resp.json()
                assert data["started_at"] == first_data["started_at"]