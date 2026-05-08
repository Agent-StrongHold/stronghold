"""BDD-style integration tests for the Canvas Studio REST API.

Each test class maps to one Gherkin feature from canvas-studio.yaml.
Tests exercise the FastAPI routes directly via TestClient with faked
CanvasStore, ImageGenClient, and CompositorService — no database, no
network calls.

All response shapes mirror the acceptance_criteria in spec 1189.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared fakes (mirrors tests/fakes.py, localised here until fakes.py is
# extended with canvas fakes in the implementation PR)
# ---------------------------------------------------------------------------

def _new_id() -> str:
    return str(uuid.uuid4())


@dataclass
class CanvasRecord:
    id: str = field(default_factory=_new_id)
    name: str = "test-canvas"
    width: int = 1024
    height: int = 1024
    background_color: str = "#FFFFFF"
    org_id: str = "org-test"
    layer_count: int = 0
    archived_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_archived(self) -> bool:
        return self.archived_at is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "width": self.width,
            "height": self.height, "background_color": self.background_color,
            "org_id": self.org_id, "layer_count": self.layer_count,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class LayerRecord:
    id: str = field(default_factory=_new_id)
    canvas_id: str = ""
    name: str = "layer"
    layer_type: str = "background"
    z_index: int = 0
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    blend_mode: str = "normal"
    visible: bool = True
    locked: bool = False
    image_path: str | None = None
    prompt: str | None = None
    model_id: str | None = None
    tier: str = "draft"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "canvas_id": self.canvas_id, "name": self.name,
            "layer_type": self.layer_type, "z_index": self.z_index,
            "x": self.x, "y": self.y, "scale": self.scale,
            "rotation": self.rotation, "opacity": self.opacity,
            "blend_mode": self.blend_mode, "visible": self.visible,
            "locked": self.locked, "image_path": self.image_path,
            "prompt": self.prompt, "model_id": self.model_id,
            "tier": self.tier,
        }


@dataclass
class GenerationJobRecord:
    id: str = field(default_factory=_new_id)
    layer_id: str = ""
    canvas_id: str = ""
    action: str = "generate"
    status: str = "pending"
    model_id: str = "test-model"
    prompt: str = ""
    result_paths: list[str] = field(default_factory=list)
    selected_index: int | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_terminal(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "layer_id": self.layer_id, "canvas_id": self.canvas_id,
            "action": self.action, "status": self.status, "model_id": self.model_id,
            "prompt": self.prompt, "result_paths": self.result_paths,
            "selected_index": self.selected_index, "error_message": self.error_message,
        }


class FakeCanvasStore:
    def __init__(self) -> None:
        self._canvases: dict[str, CanvasRecord] = {}
        self._layers: dict[str, LayerRecord] = {}
        self._jobs: dict[str, GenerationJobRecord] = {}

    def seed_canvas(self, **kw: Any) -> CanvasRecord:
        c = CanvasRecord(**kw)
        self._canvases[c.id] = c
        return c

    def seed_layer(self, canvas_id: str, **kw: Any) -> LayerRecord:
        layer = LayerRecord(canvas_id=canvas_id, **kw)
        self._layers[layer.id] = layer
        self._canvases[canvas_id].layer_count += 1
        return layer

    def seed_job(self, **kw: Any) -> GenerationJobRecord:
        job = GenerationJobRecord(**kw)
        self._jobs[job.id] = job
        return job

    async def list_canvases(self, org_id: str, include_archived: bool = False) -> list[CanvasRecord]:
        return [
            c for c in self._canvases.values()
            if c.org_id == org_id and (include_archived or c.archived_at is None)
        ]

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None:
        return self._canvases.get(canvas_id)

    async def create_canvas(self, **kw: Any) -> CanvasRecord:
        c = CanvasRecord(**kw)
        self._canvases[c.id] = c
        return c

    async def update_canvas(self, canvas: CanvasRecord) -> CanvasRecord:
        self._canvases[canvas.id] = canvas
        return canvas

    async def get_layer(self, layer_id: str) -> LayerRecord | None:
        return self._layers.get(layer_id)

    async def list_layers(self, canvas_id: str) -> list[LayerRecord]:
        return sorted(
            [l for l in self._layers.values() if l.canvas_id == canvas_id],
            key=lambda l: l.z_index,
        )

    async def add_layer(self, canvas_id: str, **kw: Any) -> LayerRecord:
        if self._canvases[canvas_id].layer_count >= 50:
            from stronghold.types.canvas import LayerLimitExceededError  # noqa: PLC0415
            raise LayerLimitExceededError(f"canvas {canvas_id!r} at layer limit")
        existing = [l for l in self._layers.values() if l.canvas_id == canvas_id]
        auto_z = max((l.z_index for l in existing), default=-1) + 1
        z_given = kw.pop("z_index", None)
        z = z_given if z_given is not None else auto_z
        layer = LayerRecord(canvas_id=canvas_id, z_index=z, **kw)
        self._layers[layer.id] = layer
        self._canvases[canvas_id].layer_count += 1
        return layer

    async def update_layer(self, layer: LayerRecord) -> LayerRecord:
        self._layers[layer.id] = layer
        return layer

    async def remove_layer(self, layer_id: str) -> None:
        layer = self._layers.pop(layer_id, None)
        if layer:
            self._canvases[layer.canvas_id].layer_count -= 1
            for l in self._layers.values():
                if l.canvas_id == layer.canvas_id and l.z_index > layer.z_index:
                    l.z_index -= 1

    async def reorder_layers(
        self,
        canvas_id: str,
        assignments: list[dict[str, Any]],
    ) -> list[LayerRecord]:
        from stronghold.types.canvas import DuplicateZIndexError, IncompleteReorderError  # noqa: PLC0415

        z_values = [a["z_index"] for a in assignments]
        if len(z_values) != len(set(z_values)):
            raise DuplicateZIndexError("duplicate z_index values in reorder request")

        existing_ids = {l.id for l in self._layers.values() if l.canvas_id == canvas_id}
        request_ids = {str(a["layer_id"]) for a in assignments}
        if existing_ids != request_ids:
            raise IncompleteReorderError(
                f"reorder covers {len(request_ids)} layers but canvas has {len(existing_ids)}"
            )

        id_to_z = {a["layer_id"]: a["z_index"] for a in assignments}
        updated = []
        for layer in self._layers.values():
            if layer.canvas_id == canvas_id:
                layer.z_index = id_to_z[layer.id]
                updated.append(layer)
        return sorted(updated, key=lambda l: l.z_index)

    async def save_composite(self, result: Any) -> Any:
        self._composites = getattr(self, "_composites", {})
        self._composites[result.canvas_id] = result
        return result

    async def latest_composite(self, canvas_id: str) -> Any | None:
        self._composites = getattr(self, "_composites", {})
        return self._composites.get(canvas_id)

    async def get_job(self, job_id: str) -> GenerationJobRecord | None:
        return self._jobs.get(job_id)

    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None:
        for job in self._jobs.values():
            if job.layer_id == layer_id and job.status in ("pending", "running"):
                return job
        return None

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return job

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord:
        self._jobs[job.id] = job
        return job


class FakeExecutor:
    """Pre-programmed executor for route tests."""

    def __init__(self, store: FakeCanvasStore) -> None:
        self._store = store
        self.start_job_error: Exception | None = None
        self.accept_result: tuple[GenerationJobRecord, LayerRecord] | None = None
        self.accept_error: Exception | None = None

    async def start_job(self, **kw: Any) -> GenerationJobRecord:
        if self.start_job_error:
            raise self.start_job_error
        job = GenerationJobRecord(
            layer_id=kw.get("layer_id", ""),
            canvas_id=kw.get("canvas_id", ""),
            action=kw.get("action", "generate"),
            model_id=kw.get("model_id", "test-model"),
            prompt=kw.get("prompt", ""),
            status="pending",
        )
        await self._store.create_job(job)
        return job

    async def accept_variant(
        self, job_id: str, variant_index: int
    ) -> tuple[GenerationJobRecord, LayerRecord]:
        if self.accept_error:
            raise self.accept_error
        if self.accept_result:
            return self.accept_result
        job = await self._store.get_job(job_id)
        assert job is not None
        layer = await self._store.get_layer(job.layer_id)
        assert layer is not None
        job.selected_index = variant_index
        layer.image_path = job.result_paths[variant_index]
        return job, layer

    async def cancel_job(self, job_id: str) -> GenerationJobRecord:
        job = await self._store.get_job(job_id)
        assert job is not None
        job.status = "cancelled"
        return job


class FakeCompositorService:
    """Returns a white PNG for any composite request."""

    async def composite(self, canvas: CanvasRecord, layers: list[LayerRecord]) -> Any:
        import io
        from PIL import Image  # type: ignore[import]

        img = Image.new("RGBA", (canvas.width, canvas.height), (255, 255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        @dataclass
        class _Result:
            canvas_id: str = canvas.id
            image_bytes: bytes = field(default_factory=bytes)
            width: int = canvas.width
            height: int = canvas.height
            layer_snapshot: list[Any] = field(default_factory=list)
            created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

        return _Result(image_bytes=buf.getvalue())


# ---------------------------------------------------------------------------
# App factory (used per test class to get a clean dependency graph)
# ---------------------------------------------------------------------------

def _make_app(store: FakeCanvasStore, executor: FakeExecutor) -> FastAPI:
    """
    Constructs a minimal FastAPI app wired to the canvas routes with faked deps.
    Replace with the real factory once routes/canvas.py exists.
    """
    from stronghold.api.routes.canvas import make_canvas_router  # type: ignore[import]
    from stronghold.api.deps import get_auth_context  # type: ignore[import]
    from stronghold.types.auth import AuthContext  # type: ignore[import]

    app = FastAPI()
    app.include_router(
        make_canvas_router(
            store=store,
            executor=executor,
            compositor=FakeCompositorService(),
        ),
        prefix="/api/canvas",
    )

    # Inject a fake auth context (org-test, with canvas roles)
    async def _fake_auth() -> AuthContext:
        return AuthContext(
            user_id="user-1",
            org_id="org-test",
            roles=frozenset(["canvas_read", "canvas_write"]),
        )

    app.dependency_overrides[get_auth_context] = _fake_auth
    return app


# ---------------------------------------------------------------------------
# Feature: Canvas CRUD
# ---------------------------------------------------------------------------

class TestCanvasCRUD:
    """
    Feature: Canvas lifecycle — create, read, update, soft-delete
    """

    def test_create_canvas_valid(self) -> None:
        """
        Given valid dimensions (1024×1024)
        When POST /api/canvas
        Then 201 with canvas record including id, name, dimensions
        """
        store = FakeCanvasStore()
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post("/api/canvas", json={"name": "hero-art", "width": 1024, "height": 1024})

        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "hero-art"
        assert body["width"] == 1024
        assert body["height"] == 1024
        assert "id" in body
        assert body["layer_count"] == 0

    def test_create_canvas_not_divisible_by_8(self) -> None:
        """
        Given width=1025 (not divisible by 8)
        When POST /api/canvas
        Then 422 with field error NOT_DIVISIBLE_BY_8
        """
        store = FakeCanvasStore()
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post("/api/canvas", json={"name": "bad", "width": 1025, "height": 1024})

        assert resp.status_code == 422
        error = resp.json()
        assert any(
            e.get("code") == "NOT_DIVISIBLE_BY_8" or "divisible" in str(e).lower()
            for e in error.get("detail", [error])
        )

    def test_create_canvas_below_minimum(self) -> None:
        """
        Given width=32 (below 64 minimum)
        When POST /api/canvas
        Then 422
        """
        store = FakeCanvasStore()
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post("/api/canvas", json={"name": "tiny", "width": 32, "height": 64})
        assert resp.status_code == 422

    def test_create_canvas_above_maximum(self) -> None:
        """
        Given width=9000 (above 8192 maximum)
        When POST /api/canvas
        Then 422
        """
        store = FakeCanvasStore()
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post("/api/canvas", json={"name": "huge", "width": 9000, "height": 1024})
        assert resp.status_code == 422

    def test_list_excludes_archived(self) -> None:
        """
        Given one archived and one active canvas in the same org
        When GET /api/canvas
        Then only the active canvas appears
        """
        store = FakeCanvasStore()
        active = store.seed_canvas(name="active", org_id="org-test")
        archived = store.seed_canvas(
            name="archived",
            org_id="org-test",
            archived_at=datetime.now(UTC),
        )
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get("/api/canvas")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "active" in names
        assert "archived" not in names

    def test_list_includes_archived_when_requested(self) -> None:
        """
        Given an archived canvas
        When GET /api/canvas?include_archived=true
        Then the archived canvas appears
        """
        store = FakeCanvasStore()
        store.seed_canvas(name="archived", org_id="org-test", archived_at=datetime.now(UTC))
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get("/api/canvas?include_archived=true")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "archived" in names

    def test_get_archived_canvas_returns_410(self) -> None:
        """
        Given an archived canvas
        When GET /api/canvas/{id}
        Then 410 Gone
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(archived_at=datetime.now(UTC))
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/{canvas.id}")
        assert resp.status_code == 410

    def test_cross_org_canvas_returns_404(self) -> None:
        """
        Given a canvas belonging to org-xyz (caller is org-test)
        When GET /api/canvas/{id}
        Then 404 (not 403 — no enumeration)
        """
        store = FakeCanvasStore()
        other_canvas = store.seed_canvas(org_id="org-xyz")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/{other_canvas.id}")
        assert resp.status_code == 404

    def test_patch_canvas_name(self) -> None:
        """
        Given a canvas with name='old'
        When PATCH /api/canvas/{id} with name='new'
        Then 200 and body.name == 'new'
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(name="old", org_id="org-test")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.patch(f"/api/canvas/{canvas.id}", json={"name": "new"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "new"

    def test_patch_dimensions_with_layers_rejected(self) -> None:
        """
        Given a canvas with 1 layer
        When PATCH with width=512
        Then 409 CANVAS_HAS_LAYERS
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        store.seed_layer(canvas.id)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.patch(f"/api/canvas/{canvas.id}", json={"width": 512})
        assert resp.status_code == 409
        assert resp.json().get("code") == "CANVAS_HAS_LAYERS"

    def test_delete_archives_canvas(self) -> None:
        """
        Given an active canvas
        When DELETE /api/canvas/{id}
        Then 200 and canvas.archived_at is set
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.delete(f"/api/canvas/{canvas.id}")
        assert resp.status_code == 200

        updated = store._canvases[canvas.id]
        assert updated.archived_at is not None


# ---------------------------------------------------------------------------
# Feature: Layer CRUD
# ---------------------------------------------------------------------------

class TestLayerCRUD:
    """
    Feature: Layer stack management — CRUD, ordering, lock
    """

    def test_add_first_layer_gets_z_index_0(self) -> None:
        """
        Given a canvas with no layers
        When POST /api/canvas/{id}/layers with name='sky' layer_type='background'
        Then 201 and layer.z_index == 0
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers",
            json={"name": "sky", "layer_type": "background"},
        )
        assert resp.status_code == 201
        assert resp.json()["z_index"] == 0

    def test_add_second_layer_gets_z_index_1(self) -> None:
        """
        Given a canvas with one layer (z=0)
        When I add a second layer
        Then second.z_index == 1
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        store.seed_layer(canvas.id, name="bg", z_index=0)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers",
            json={"name": "hero", "layer_type": "character"},
        )
        assert resp.status_code == 201
        assert resp.json()["z_index"] == 1

    def test_layer_ceiling_enforced(self) -> None:
        """
        Given a canvas with 50 layers
        When I add one more
        Then 409 LAYER_LIMIT_EXCEEDED
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        for i in range(50):
            store.seed_layer(canvas.id, z_index=i, name=f"layer-{i}")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers",
            json={"name": "overflow", "layer_type": "object"},
        )
        assert resp.status_code == 409
        assert resp.json().get("code") == "LAYER_LIMIT_EXCEEDED"

    def test_locked_layer_rejects_position_patch(self) -> None:
        """
        Given a locked layer
        When PATCH with x=100
        Then 409 LAYER_LOCKED
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id, locked=True)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.patch(
            f"/api/canvas/{canvas.id}/layers/{layer.id}",
            json={"x": 100},
        )
        assert resp.status_code == 409
        assert resp.json().get("code") == "LAYER_LOCKED"

    def test_locked_layer_allows_name_patch(self) -> None:
        """
        Given a locked layer
        When PATCH with name='renamed'
        Then 200 (name is not a positional field)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id, locked=True, name="old")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.patch(
            f"/api/canvas/{canvas.id}/layers/{layer.id}",
            json={"name": "renamed"},
        )
        assert resp.status_code == 200

    def test_rotation_wraps_at_360(self) -> None:
        """
        Given rotation=400.0 in the PATCH body
        When PATCH is processed
        Then layer.rotation stored as 40.0
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.patch(
            f"/api/canvas/{canvas.id}/layers/{layer.id}",
            json={"rotation": 400.0},
        )
        assert resp.status_code == 200
        assert abs(resp.json()["rotation"] - 40.0) < 0.01

    def test_scale_zero_rejected(self) -> None:
        """
        Given scale=0.0 in PATCH
        When PATCH is processed
        Then 422 (scale must be > 0)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.patch(
            f"/api/canvas/{canvas.id}/layers/{layer.id}",
            json={"scale": 0.0},
        )
        assert resp.status_code == 422

    def test_delete_layer_repacks_z_indices(self) -> None:
        """
        Given layers at z=[0,1,2,3] and we delete z=1
        When DELETE /api/canvas/{id}/layers/{mid.id}
        Then remaining layers have z=[0,1,2] (dense)
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layers = [store.seed_layer(canvas.id, z_index=i, name=f"L{i}") for i in range(4)]
        mid = layers[1]
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.delete(f"/api/canvas/{canvas.id}/layers/{mid.id}")
        assert resp.status_code == 200

        remaining = sorted(
            [l for l in store._layers.values() if l.canvas_id == canvas.id],
            key=lambda l: l.z_index,
        )
        assert [l.z_index for l in remaining] == [0, 1, 2]

    def test_reorder_atomically(self) -> None:
        """
        Given layers A(z=0) B(z=1) C(z=2)
        When POST /api/canvas/{id}/layers/reorder [{A,2},{B,0},{C,1}]
        Then 200 and z_indices are updated
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        a = store.seed_layer(canvas.id, z_index=0, name="A")
        b = store.seed_layer(canvas.id, z_index=1, name="B")
        c = store.seed_layer(canvas.id, z_index=2, name="C")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/reorder",
            json=[
                {"layer_id": a.id, "z_index": 2},
                {"layer_id": b.id, "z_index": 0},
                {"layer_id": c.id, "z_index": 1},
            ],
        )
        assert resp.status_code == 200
        assert store._layers[a.id].z_index == 2
        assert store._layers[b.id].z_index == 0
        assert store._layers[c.id].z_index == 1

    def test_reorder_duplicate_z_index_rejected(self) -> None:
        """
        Given layers A and B
        When reorder assigns both z_index=0
        Then 422 DUPLICATE_Z_INDEX
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        a = store.seed_layer(canvas.id, z_index=0, name="A")
        b = store.seed_layer(canvas.id, z_index=1, name="B")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/reorder",
            json=[
                {"layer_id": a.id, "z_index": 0},
                {"layer_id": b.id, "z_index": 0},
            ],
        )
        assert resp.status_code == 422
        assert resp.json().get("code") == "DUPLICATE_Z_INDEX"

    def test_reorder_missing_layer_rejected(self) -> None:
        """
        Given 3 layers, reorder only sends 2 assignments
        Then 422 INCOMPLETE_REORDER
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        a = store.seed_layer(canvas.id, z_index=0)
        b = store.seed_layer(canvas.id, z_index=1)
        _ = store.seed_layer(canvas.id, z_index=2)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/reorder",
            json=[
                {"layer_id": a.id, "z_index": 0},
                {"layer_id": b.id, "z_index": 1},
            ],
        )
        assert resp.status_code == 422
        assert resp.json().get("code") == "INCOMPLETE_REORDER"


# ---------------------------------------------------------------------------
# Feature: Generation jobs
# ---------------------------------------------------------------------------

class TestGenerationJobs:
    """
    Feature: Generation job lifecycle
    """

    def test_generate_returns_202_with_job_id(self) -> None:
        """
        When POST /api/canvas/{id}/layers/{lid}/generate
        Then 202 Accepted with {job_id, status='pending'}
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "generate", "model_id": "test-draft-model", "prompt": "sunset"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending"
        assert "job_id" in body

    def test_text_layer_rejects_generate(self) -> None:
        """
        Given layer_type='text'
        When POST generate
        Then 400 TEXT_LAYER_NO_GEN
        """
        from stronghold.tools.canvas_executor import TextLayerNoGenError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id, layer_type="text")
        executor = FakeExecutor(store)
        executor.start_job_error = TextLayerNoGenError("text layer")
        client = TestClient(_make_app(store, executor))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "generate", "model_id": "test-model", "prompt": "hello"},
        )
        assert resp.status_code == 400
        assert resp.json().get("code") == "TEXT_LAYER_NO_GEN"

    def test_concurrent_job_returns_409(self) -> None:
        """
        Given a pending job already exists
        When a second generate call arrives
        Then 409 JOB_IN_PROGRESS
        """
        from stronghold.tools.canvas_executor import JobInProgressError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="pending")
        executor = FakeExecutor(store)
        executor.start_job_error = JobInProgressError("already running")
        client = TestClient(_make_app(store, executor))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "generate", "model_id": "test-model", "prompt": "sky"},
        )
        assert resp.status_code == 409
        assert resp.json().get("code") == "JOB_IN_PROGRESS"

    def test_unknown_model_returns_400(self) -> None:
        """
        Given model_id not in the registry
        When POST generate
        Then 400 UNKNOWN_MODEL
        """
        from stronghold.tools.canvas_executor import UnknownModelError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        executor = FakeExecutor(store)
        executor.start_job_error = UnknownModelError("no-such-model")
        client = TestClient(_make_app(store, executor))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "generate", "model_id": "no-such-model", "prompt": "sky"},
        )
        assert resp.status_code == 400
        assert resp.json().get("code") == "UNKNOWN_MODEL"

    def test_prompt_blocked_returns_400(self) -> None:
        """
        Given Warden blocks the prompt
        When POST generate
        Then 400 PROMPT_BLOCKED
        """
        from stronghold.tools.canvas_executor import PromptBlockedError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        executor = FakeExecutor(store)
        executor.start_job_error = PromptBlockedError("forbidden")
        client = TestClient(_make_app(store, executor))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "generate", "model_id": "test-model", "prompt": "forbidden content"},
        )
        assert resp.status_code == 400
        assert resp.json().get("code") == "PROMPT_BLOCKED"

    def test_refine_no_source_returns_400(self) -> None:
        """
        Given layer has no image_path and action='refine'
        When POST generate
        Then 400 REFINE_NO_SOURCE
        """
        from stronghold.tools.canvas_executor import RefineNoSourceError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id, image_path=None)
        executor = FakeExecutor(store)
        executor.start_job_error = RefineNoSourceError("no image")
        client = TestClient(_make_app(store, executor))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "refine", "model_id": "test-model", "prompt": "fix hands"},
        )
        assert resp.status_code == 400
        assert resp.json().get("code") == "REFINE_NO_SOURCE"

    def test_get_job_returns_status(self) -> None:
        """
        Given a job in the store
        When GET /api/canvas/jobs/{jid}
        Then 200 with the job record
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png"],
        )
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/jobs/{job.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "done"
        assert body["result_paths"] == ["https://cdn/img-0.png"]

    def test_accept_variant_updates_layer(self) -> None:
        """
        Given a done job with 2 result_paths
        When POST /api/canvas/jobs/{jid}/accept/1
        Then 200 and layer.image_path == result_paths[1]
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png", "https://cdn/img-1.png"],
        )
        executor = FakeExecutor(store)
        executor.accept_result = (job, layer)
        client = TestClient(_make_app(store, executor))

        resp = client.post(f"/api/canvas/jobs/{job.id}/accept/1")
        assert resp.status_code == 200

    def test_accept_out_of_range_returns_422(self) -> None:
        """
        Given variant_index=5 and result_paths has 2 entries
        When POST accept/5
        Then 422 VARIANT_INDEX_OUT_OF_RANGE
        """
        from stronghold.tools.canvas_executor import VariantIndexOutOfRangeError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(
            layer_id=layer.id,
            canvas_id=canvas.id,
            status="done",
            result_paths=["https://cdn/img-0.png", "https://cdn/img-1.png"],
        )
        executor = FakeExecutor(store)
        executor.accept_error = VariantIndexOutOfRangeError("5 >= 2")
        client = TestClient(_make_app(store, executor))

        resp = client.post(f"/api/canvas/jobs/{job.id}/accept/5")
        assert resp.status_code == 422
        assert resp.json().get("code") == "VARIANT_INDEX_OUT_OF_RANGE"

    def test_accept_non_done_job_returns_409(self) -> None:
        """
        Given job.status == 'running'
        When POST accept/0
        Then 409 JOB_NOT_DONE
        """
        from stronghold.tools.canvas_executor import JobNotDoneError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="running")
        executor = FakeExecutor(store)
        executor.accept_error = JobNotDoneError("running")
        client = TestClient(_make_app(store, executor))

        resp = client.post(f"/api/canvas/jobs/{job.id}/accept/0")
        assert resp.status_code == 409
        assert resp.json().get("code") == "JOB_NOT_DONE"

    def test_cancel_pending_job(self) -> None:
        """
        Given a pending job
        When DELETE /api/canvas/jobs/{jid}
        Then 200 and job.status == 'cancelled'
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="pending")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.delete(f"/api/canvas/jobs/{job.id}")
        assert resp.status_code == 200
        assert store._jobs[job.id].status == "cancelled"

    def test_cancel_done_job_returns_409(self) -> None:
        """
        Given a done job
        When DELETE /api/canvas/jobs/{jid}
        Then 409
        """
        from stronghold.tools.canvas_executor import JobAlreadyTerminalError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        job = store.seed_job(layer_id=layer.id, canvas_id=canvas.id, status="done")
        executor = FakeExecutor(store)

        # Wire cancel to raise terminal error for done jobs
        original_cancel = executor.cancel_job

        async def _raising_cancel(job_id: str) -> GenerationJobRecord:
            j = await store.get_job(job_id)
            assert j is not None
            if j.status == "done":
                raise JobAlreadyTerminalError("done")
            return await original_cancel(job_id)

        executor.cancel_job = _raising_cancel  # type: ignore[method-assign]
        client = TestClient(_make_app(store, executor))

        resp = client.delete(f"/api/canvas/jobs/{job.id}")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Feature: Export
# ---------------------------------------------------------------------------

class TestExport:
    """
    Feature: Canvas export to image file
    """

    def test_export_png_returns_image(self) -> None:
        """
        Given a canvas with a composite
        When GET /api/canvas/{id}/export?format=png
        Then 200 with Content-Type image/png
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        store.seed_layer(canvas.id, image_path="https://cdn/bg.png")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/{canvas.id}/export?format=png")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/png")

    def test_export_unsupported_format_returns_400(self) -> None:
        """
        Given format=bmp (unsupported)
        When GET export
        Then 400 UNSUPPORTED_FORMAT
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/{canvas.id}/export?format=bmp")
        assert resp.status_code == 400
        assert resp.json().get("code") == "UNSUPPORTED_FORMAT"

    def test_export_quality_out_of_range_returns_422(self) -> None:
        """
        Given quality=0 (below minimum 1)
        When GET export
        Then 422
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/{canvas.id}/export?format=jpg&quality=0")
        assert resp.status_code == 422

    def test_export_archived_canvas_returns_404(self) -> None:
        """
        Given archived canvas
        When GET export
        Then 404
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test", archived_at=datetime.now(UTC))
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get(f"/api/canvas/{canvas.id}/export?format=png")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Feature: Invariant probes — spot-checks the critical invariants
# ---------------------------------------------------------------------------

class TestInvariantProbes:
    """
    Probes that verify the critical API-level invariants from spec 1189.
    These are not full end-to-end tests — they verify the contract shape.
    """

    def test_z_index_dense_after_delete(self) -> None:
        """
        Invariant z_index_dense_packing: after delete, z_indices are 0..N-1
        """
        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layers = [store.seed_layer(canvas.id, z_index=i) for i in range(5)]
        client = TestClient(_make_app(store, FakeExecutor(store)))

        # Delete z=2
        client.delete(f"/api/canvas/{canvas.id}/layers/{layers[2].id}")

        z_indices = sorted(
            l.z_index for l in store._layers.values() if l.canvas_id == canvas.id
        )
        assert z_indices == list(range(len(z_indices))), f"Non-dense z_indices: {z_indices}"

    def test_no_cross_org_data_leakage(self) -> None:
        """
        Invariant org_isolation: list never returns canvases from another org
        """
        store = FakeCanvasStore()
        store.seed_canvas(org_id="org-test", name="mine")
        store.seed_canvas(org_id="org-other", name="theirs")
        client = TestClient(_make_app(store, FakeExecutor(store)))

        resp = client.get("/api/canvas")
        names = [c["name"] for c in resp.json()]
        assert "mine" in names
        assert "theirs" not in names

    def test_error_response_no_traceback(self) -> None:
        """
        Invariant no_raw_provider_errors: error responses never expose 'Traceback'
        """
        from stronghold.tools.canvas_executor import UnknownModelError  # type: ignore[import]

        store = FakeCanvasStore()
        canvas = store.seed_canvas(org_id="org-test")
        layer = store.seed_layer(canvas.id)
        executor = FakeExecutor(store)
        executor.start_job_error = UnknownModelError(
            "Traceback (most recent call last):\n  line 1\nunknown-model-xyz"
        )
        client = TestClient(_make_app(store, executor))

        resp = client.post(
            f"/api/canvas/{canvas.id}/layers/{layer.id}/generate",
            json={"action": "generate", "model_id": "bad", "prompt": "sky"},
        )
        assert "Traceback" not in resp.text
