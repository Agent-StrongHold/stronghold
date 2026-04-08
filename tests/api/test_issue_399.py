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


class TestAttributeErrorLibraryLookup:
    def test_library_docs_lookup_on_attribute_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            error_msg = "'FastAPI' object has no attribute 'is_json'"
            resp = client.post(
                "/mcp/lookup",
                headers=AUTH_HEADER,
                json={"error": error_msg},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "library_name" in data
            assert data["library_name"] == "FastAPI"
            assert "documentation" in data
            assert "cached" in data
            assert data["cached"] is True


class TestCachedLibraryDocsPrevention:
    def test_cached_library_docs_prevents_redundant_queries(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # First call to cache the documentation
            error_msg = "No module named 'requests'"
            first_resp = client.post(
                "/mcp/lookup",
                headers=AUTH_HEADER,
                json={"error": error_msg},
            )
            assert first_resp.status_code == 200
            first_data = first_resp.json()
            assert first_data["library_name"] == "requests"
            assert "documentation" in first_data
            assert first_data["cached"] is False

            # Second call should use cached docs
            second_resp = client.post(
                "/mcp/lookup",
                headers=AUTH_HEADER,
                json={"error": error_msg},
            )
            assert second_resp.status_code == 200
            second_data = second_resp.json()
            assert second_data["library_name"] == "requests"
            assert "documentation" in second_data
            assert second_data["cached"] is True
            assert second_data["documentation"] == first_data["documentation"]


class TestSuccessfulLibraryDocsLookupOnImportError:
    def test_successful_library_docs_lookup_on_import_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            error_msg = "No module named 'redis.asyncio'"
            resp = client.post(
                "/mcp/lookup",
                headers=AUTH_HEADER,
                json={"error": error_msg},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "library_name" in data
            assert data["library_name"] == "redis.asyncio"
            assert "documentation" in data
            assert data["documentation"] is not None
            assert data["documentation"] != ""
            assert (
                "redis" in data["documentation"].lower() or "redis" in data["library_name"].lower()
            )


class TestSuccessfulLibraryDocsLookupOnAttributeError:
    def test_successful_library_docs_lookup_on_attribute_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            error_msg = "'FastAPI' object has no attribute 'is_json'"
            resp = client.post(
                "/mcp/lookup",
                headers=AUTH_HEADER,
                json={"error": error_msg},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "library_name" in data
            assert data["library_name"] == "FastAPI"
            assert "documentation" in data
            assert data["documentation"] is not None
            assert data["documentation"] != ""
            assert "FastAPI" in data["documentation"]
