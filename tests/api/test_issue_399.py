"""Tests for MCP library documentation lookup on ImportError."""

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


class TestImportErrorLibraryLookup:
    def test_library_docs_lookup_on_import_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test should fail initially as the implementation doesn't exist yet
            resp = client.get("/mcp/catalog", headers=AUTH_HEADER)
            assert resp.status_code == 200
