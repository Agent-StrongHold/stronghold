"""Tests for annotation API routes — CRUD, auth, query params."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.annotations.store import InMemoryAnnotationStore
from stronghold.api.routes.annotations import router as annotations_router
from stronghold.types.auth import AuthContext
from tests.fakes import FakeAuthProvider


def _make_app(*, auth_context: AuthContext | None = None) -> FastAPI:
    """Build a minimal FastAPI app with annotation routes and a fake container."""
    app = FastAPI()
    app.include_router(annotations_router)

    annotation_store = InMemoryAnnotationStore()
    auth_provider = FakeAuthProvider(auth_context=auth_context)

    # Minimal container-like object for the routes
    class _FakeContainer:
        def __init__(self) -> None:
            self.annotation_store = annotation_store
            self.auth_provider = auth_provider

    app.state.container = _FakeContainer()
    return app


def _org_auth(org_id: str = "org-a", user_id: str = "u1") -> AuthContext:
    return AuthContext(
        user_id=user_id,
        username="tester",
        org_id=org_id,
        roles=frozenset({"user"}),
        auth_method="api_key",
    )


class TestAnnotationRouteCreate:
    def test_create_annotation_returns_200(self) -> None:
        """POST /v1/stronghold/annotations creates and returns annotation."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/annotations",
                json={
                    "session_id": "s1",
                    "tags": ["compliance"],
                    "rating": 4,
                    "note": "Good conversation",
                },
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] != ""
            assert data["session_id"] == "s1"
            assert data["tags"] == ["compliance"]
            assert data["rating"] == 4
            assert data["note"] == "Good conversation"
            assert data["org_id"] == "org-a"
            assert data["user_id"] == "u1"

    def test_create_annotation_no_auth_returns_401(self) -> None:
        """POST without auth header returns 401."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s1", "tags": ["test"]},
            )
            assert resp.status_code == 401

    def test_create_annotation_invalid_rating_returns_400(self) -> None:
        """POST with rating=0 returns 400."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s1", "rating": 0},
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 400


class TestAnnotationRouteGetBySession:
    def test_get_annotations_returns_list(self) -> None:
        """GET /v1/stronghold/annotations/{session_id} returns annotations."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            # Create one first
            client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s1", "tags": ["test"]},
                headers={"Authorization": "Bearer test-key"},
            )
            resp = client.get(
                "/v1/stronghold/annotations/s1",
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["tags"] == ["test"]

    def test_get_annotations_no_auth_returns_401(self) -> None:
        """GET without auth header returns 401."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/annotations/s1")
            assert resp.status_code == 401


class TestAnnotationRouteQueryByTag:
    def test_query_by_tag(self) -> None:
        """GET /v1/stronghold/annotations?tag=X filters by tag."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s1", "tags": ["compliance"]},
                headers={"Authorization": "Bearer test-key"},
            )
            client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s2", "tags": ["training"]},
                headers={"Authorization": "Bearer test-key"},
            )
            resp = client.get(
                "/v1/stronghold/annotations?tag=compliance",
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert "compliance" in data[0]["tags"]


class TestAnnotationRouteQueryByRating:
    def test_query_by_rating_below(self) -> None:
        """GET /v1/stronghold/annotations?rating_below=N filters by rating."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s1", "rating": 2},
                headers={"Authorization": "Bearer test-key"},
            )
            client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s2", "rating": 5},
                headers={"Authorization": "Bearer test-key"},
            )
            resp = client.get(
                "/v1/stronghold/annotations?rating_below=3",
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["rating"] == 2


class TestAnnotationRouteDelete:
    def test_delete_annotation(self) -> None:
        """DELETE /v1/stronghold/annotations/{id} removes the annotation."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/annotations",
                json={"session_id": "s1", "tags": ["delete-me"]},
                headers={"Authorization": "Bearer test-key"},
            )
            ann_id = resp.json()["id"]

            resp = client.delete(
                f"/v1/stronghold/annotations/{ann_id}",
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["deleted"] is True

    def test_delete_nonexistent_returns_404(self) -> None:
        """DELETE on a nonexistent annotation returns 404."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.delete(
                "/v1/stronghold/annotations/no-such-id",
                headers={"Authorization": "Bearer test-key"},
            )
            assert resp.status_code == 404

    def test_delete_no_auth_returns_401(self) -> None:
        """DELETE without auth header returns 401."""
        app = _make_app(auth_context=_org_auth())
        with TestClient(app) as client:
            resp = client.delete("/v1/stronghold/annotations/some-id")
            assert resp.status_code == 401
