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


class TestGetTask:
    def test_retrieve_existing_task(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            task_id = "task-123"
            payload = {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "result": {"output": "test result"},
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "callback_url": "https://example.com/callback",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:01:00Z",
            }
            # First create the task
            client.post("/v1/tasks", json=payload, headers=AUTH_HEADER)

            # Then retrieve it
            get_resp = client.get(f"/v1/tasks/{task_id}", headers=AUTH_HEADER)
            assert get_resp.status_code == 200
            data = get_resp.json()

            # Verify all fields match
            assert data["task_id"] == task_id
            assert data["status"] == payload["status"]
            assert data["progress"] == payload["progress"]
            assert data["result"] == payload["result"]
            assert data["usage"] == payload["usage"]
            assert data["callback_url"] == payload["callback_url"]
            assert data["created_at"] == payload["created_at"]
            assert data["updated_at"] == payload["updated_at"]


class TestUpdateTask:
    def test_update_task_status_and_progress(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            task_id = "task-456"
            initial_payload = {
                "task_id": task_id,
                "status": "pending",
                "progress": 50,
                "result": None,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "callback_url": "https://example.com/callback",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
            # Create the task
            client.post("/v1/tasks", json=initial_payload, headers=AUTH_HEADER)

            # Update the task status and progress
            update_payload = {
                "status": "completed",
                "progress": 100,
                "updated_at": "2024-01-01T00:02:00Z",
            }
            update_resp = client.patch(
                f"/v1/tasks/{task_id}", json=update_payload, headers=AUTH_HEADER
            )
            assert update_resp.status_code == 200

            # Verify the update in the database
            get_resp = client.get(f"/v1/tasks/{task_id}", headers=AUTH_HEADER)
            assert get_resp.status_code == 200
            data = get_resp.json()

            assert data["task_id"] == task_id
            assert data["status"] == update_payload["status"]
            assert data["progress"] == update_payload["progress"]
            assert data["result"] == initial_payload["result"]
            assert data["usage"] == initial_payload["usage"]
            assert data["callback_url"] == initial_payload["callback_url"]
            assert data["created_at"] == initial_payload["created_at"]
            assert data["updated_at"] == update_payload["updated_at"]


class TestTaskValidation:
    def test_missing_task_id_returns_validation_error(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                # Missing task_id
                "status": "pending",
                "progress": 0,
                "result": None,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                "callback_url": "https://example.com/callback",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
            }
            resp = client.post("/v1/tasks", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 422  # Validation error
            data = resp.json()
            assert "detail" in data
            assert any(
                "task_id" in str(err["loc"]) and err["type"] == "missing" for err in data["detail"]
            )
