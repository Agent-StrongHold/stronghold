"""Tests for task persistence via API."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.tasks import router as tasks_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(tasks_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestCreateTask:
    def test_task_is_persisted_in_database(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                "task_id": "task-123",
                "status": "pending",
                "progress": 0,
                "result": None,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "callback_url": "https://example.com/callback",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
            resp = client.post("/v1/tasks", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 201

            # This will fail until the implementation is added
            task_id = payload["task_id"]
            get_resp = client.get(f"/v1/tasks/{task_id}", headers=AUTH_HEADER)
            assert get_resp.status_code == 200
            data = get_resp.json()
            assert data["task_id"] == task_id
            assert data["status"] == payload["status"]
            assert data["progress"] == payload["progress"]
            assert data["result"] == payload["result"]
            assert data["usage"] == payload["usage"]
            assert data["callback_url"] == payload["callback_url"]
