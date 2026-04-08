"""Tests for skill installation."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.skills import router as skills_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(skills_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestSkillInstall:
    def test_install_skill_from_github_repo(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            repo_url = "https://github.com/user/skill-repo"
            resp = client.post(
                "/skills/install", json={"repository": repo_url}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200

    def test_install_skill_with_invalid_url_format(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            invalid_url = "invalid-url"
            resp = client.post(
                "/skills/install", json={"repository": invalid_url}, headers=AUTH_HEADER
            )
            assert resp.status_code == 422
            assert "Invalid repository URL format" in resp.text

    def test_install_skill_with_nonexistent_repo(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            nonexistent_repo = "https://github.com/nonexistent/repo"
            resp = client.post(
                "/skills/install", json={"repository": nonexistent_repo}, headers=AUTH_HEADER
            )
            assert resp.status_code == 400
            assert "Repository not found or inaccessible" in resp.text

    def test_install_skill_extracts_correct_skill_name(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            repo_url = "https://github.com/user/skill-repo"
            resp = client.post(
                "/skills/install", json={"repository": repo_url}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["skill_name"] == "skill-repo"

    def test_install_skill_fails_with_url_without_https(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            invalid_url = "http://github.com/user/skill-repo"
            resp = client.post(
                "/skills/install", json={"repository": invalid_url}, headers=AUTH_HEADER
            )
            assert resp.status_code == 422
            assert "Invalid repository URL format" in resp.text
