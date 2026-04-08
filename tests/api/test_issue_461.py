"""Tests for request context propagation through async pipeline."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.conductor import router as conductor_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(conductor_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestRequestContextPropagation:
    def test_request_context_available_in_pipeline(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/conductor",
                headers=AUTH_HEADER,
                json={"input": "test request", "metadata": {"request_id": "req-123"}},
            )
            assert resp.status_code == 200
