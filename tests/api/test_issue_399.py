"""Tests for library documentation lookup from ImportError."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.mcp import router as mcp_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(mcp_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


class TestImportErrorLibraryDocs:
    def test_library_docs_lookup_on_import_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Simulate ImportError for redis.asyncio.Redis
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"image": "ghcr.io/strongholdai/redis:latest", "name": "redis"},
                headers=AUTH_HEADER,
            )
            # Expect failure due to ImportError handling
            assert resp.status_code == 400
            # Verify the error message contains "redis" library name
            assert "redis" in resp.json()["detail"].lower()
            # Verify the error indicates documentation lookup was attempted
            assert "documentation" in resp.json()["detail"].lower()
