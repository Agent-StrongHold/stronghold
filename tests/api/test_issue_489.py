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
