from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.admin import router as admin_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test-admin"}

@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(admin_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app

class TestAdminConfigEndpoint:
    def test_admin_config_returns_200_with_valid_auth(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=AUTH_HEADER)
            assert resp.status_code == 200

    def test_admin_config_response_structure(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=AUTH_HEADER)
            data = resp.json()

            assert isinstance(data, dict)
            assert "litellm_url" in data
            assert "auth_method" in data
            assert "rate_limit" in data
            assert "cors_origins" in data

    def test_admin_config_response_has_no_secrets(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=AUTH_HEADER)
            data = resp.json()

            assert "password" not in data
            assert "secret" not in data
            assert "key" not in data

    def test_admin_config_returns_401_without_auth(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config")
            assert resp.status_code == 401
            error_data = resp.json()
            assert "detail" in error_data
            assert "authentication" in error_data["detail"].lower()

    def test_admin_config_returns_403_for_non_admin_user(self, app: FastAPI) -> None:
        non_admin_header = {"Authorization": "Bearer sk-test"}
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=non_admin_header)
            assert resp.status_code == 403
            error_data = resp.json()
            assert "detail" in error_data
            assert "permission" in error_data["detail"].lower()

    def test_admin_config_response_values_are_strings(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=AUTH_HEADER)
            data = resp.json()

            assert isinstance(data["litellm_url"], str)
            assert isinstance(data["auth_method"], str)
            assert isinstance(data["rate_limit"], str)
            assert isinstance(data["cors_origins"], list)

    def test_admin_config_returns_401_for_unauthenticated_user(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config")
            assert resp.status_code == 401
            error_data = resp.json()
            assert "detail" in error_data
            assert "authentication" in error_data["detail"].lower()

    def test_admin_config_returns_403_for_non_admin_with_permission_message(self, app: FastAPI) -> None:
        non_admin_header = {"Authorization": "Bearer sk-test"}
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=non_admin_header)
            assert resp.status_code == 403
            error_data = resp.json()
            assert "detail" in error_data
            assert "permission denied" in error_data["detail"].lower()

    def test_admin_config_returns_valid_json_response(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=AUTH_HEADER)
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "application/json"
            data = resp.json()
            assert isinstance(data, dict)
            assert "litellm_url" in data
            assert "auth_method" in data
            assert "rate_limit" in data
            assert "cors_origins" in data
            assert all(isinstance(v, (str, list)) for k, v in data.items() if k != "cors_origins")
            assert isinstance(data["cors_origins"], list)

    def test_unauthenticated_user_gets_401_with_authentication_error_message(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config")
            assert resp.status_code == 401
            error_data = resp.json()
            assert "detail" in error_data
            assert isinstance(error_data["detail"], str)
            assert "authentication" in error_data["detail"].lower()
            assert "required" in error_data["detail"].lower() or "credentials" in error_data["detail"].lower()

    def test_non_admin_user_gets_403_with_permission_denied_message(self, app: FastAPI) -> None:
        non_admin_header = {"Authorization": "Bearer sk-test"}
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/config", headers=non_admin_header)
            assert resp.status_code == 403
            error_data = resp.json()
            assert "detail" in error_data
            assert isinstance(error_data["detail"], str)
            assert "permission denied" in error_data["detail"].lower()