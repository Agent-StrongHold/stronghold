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
            assert isinstance(data.get("uptime_seconds"), float)
            assert isinstance(data.get("started_at"), str)
            assert data.get("service") == "stronghold"

    def test_uptime_increases_over_time(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # First request
            resp1 = client.get("/v1/stronghold/status/uptime")
            assert resp1.status_code == 200
            data1 = resp1.json()
            uptime1 = data1["uptime_seconds"]

            # Second request after a small delay
            import time

            time.sleep(0.1)

            resp2 = client.get("/v1/stronghold/status/uptime")
            assert resp2.status_code == 200
            data2 = resp2.json()
            uptime2 = data2["uptime_seconds"]

            # Uptime should have increased
            assert uptime2 > uptime1
