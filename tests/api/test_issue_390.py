"""Tests for version endpoint."""

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


class TestVersionEndpoint:
    def test_get_version_success(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")
            assert resp.status_code == 200
            data = resp.json()
            assert "version" in data
            assert "python_version" in data
            assert "service" in data
            assert data["service"] == "stronghold"

    def test_version_field_is_populated(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "version" in data
            assert data["version"] != ""

    def test_python_version_format(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            python_version = data["python_version"]
            assert isinstance(python_version, str)
            assert python_version.startswith("3.")
            assert "." in python_version
            assert len(python_version.split(".")) >= 2


class TestInvalidEndpoint:
    def test_invalid_endpoint_returns_404(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/invalid")
            assert resp.status_code == 404

    def test_invalid_endpoint_response_has_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/invalid").json()
            # FastAPI's default 404 shape is {"detail": "Not Found"}
            assert "detail" in data


class TestServiceName:
    def test_service_field_is_stronghold(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert data["service"] == "stronghold"


class TestResponseValidity:
    def test_response_is_valid_json(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)


class TestVersionFormat:
    def test_version_matches_semver_pattern(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            version = data["version"]
            assert isinstance(version, str)
            assert version != ""
            import re

            assert re.match(r"^\d+\.\d+\.\d+$", version)


class TestPythonVersionField:
    def test_python_version_field_is_not_empty(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            assert "python_version" in data
            assert data["python_version"] != ""


class TestVersionEndpointSuccess:
    def test_version_endpoint_success_criteria(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/version")

            # Status code should be 200
            assert resp.status_code == 200

            # Response should be valid JSON
            data = resp.json()
            assert isinstance(data, dict)

            # Response should contain required fields
            assert "version" in data
            assert "python_version" in data
            assert "service" in data

            # Service field should be set to "stronghold"
            assert data["service"] == "stronghold"


class TestVersionFieldFormat:
    def test_version_field_matches_expected_pattern(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            version = data["version"]
            assert isinstance(version, str)
            import re

            assert re.match(r"^\d+\.\d+\.\d+$", version)


class TestPythonVersionFormat:
    def test_python_version_matches_pep440_pattern(self, app: FastAPI) -> None:
        import re

        with TestClient(app) as client:
            data = client.get("/v1/stronghold/version").json()
            python_version = data["python_version"]

            # PEP 440 compliant version format: major.minor.patch[extra]
            # e.g., 3.9.7, 3.10.0rc1, 3.11.0a1
            assert re.match(r"^3\.\d+\.\d+([a-z]\d+)?$", python_version)
