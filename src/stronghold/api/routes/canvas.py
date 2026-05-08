from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from stronghold.api.deps import AuthDep  # noqa: TC001
from stronghold.types.canvas import (
    CanvasArchivedError,
    CanvasHasLayersError,
    CanvasNotFoundError,
    DuplicateZIndexError,
    IncompleteReorderError,
    JobAlreadyTerminalError,
    JobInProgressError,
    JobNotDoneError,
    JobNotFoundError,
    LayerLimitExceededError,
    LayerLockedError,
    LayerNotFoundError,
    PromptBlockedError,
    RefineNoSourceError,
    TextLayerNoGenError,
    UnknownModelError,
    UnsupportedFormatError,
    VariantIndexOutOfRangeError,
)

if TYPE_CHECKING:
    from stronghold.types.canvas import CanvasRecord

_POSITIONAL_FIELDS = frozenset(
    {"x", "y", "scale", "rotation", "opacity", "blend_mode", "visible", "z_index"}
)

_SUPPORTED_FORMATS = frozenset({"png", "jpg", "webp"})

_ERROR_MAP: dict[type, int] = {
    CanvasNotFoundError: 404,
    LayerNotFoundError: 404,
    JobNotFoundError: 404,
    CanvasArchivedError: 410,
    TextLayerNoGenError: 400,
    UnknownModelError: 400,
    PromptBlockedError: 400,
    RefineNoSourceError: 400,
    UnsupportedFormatError: 400,
    JobInProgressError: 409,
    JobNotDoneError: 409,
    JobAlreadyTerminalError: 409,
    LayerLockedError: 409,
    LayerLimitExceededError: 409,
    CanvasHasLayersError: 409,
    VariantIndexOutOfRangeError: 422,
    DuplicateZIndexError: 422,
    IncompleteReorderError: 422,
}


class _CreateCanvasBody(BaseModel):
    name: str
    width: int = Field(ge=64, le=8192)
    height: int = Field(ge=64, le=8192)
    background_color: str = "#FFFFFF"

    @field_validator("width", "height")
    @classmethod
    def _divisible_by_8(cls, v: int) -> int:
        if v % 8 != 0:
            raise ValueError("NOT_DIVISIBLE_BY_8")
        return v


class _UpdateCanvasBody(BaseModel):
    name: str | None = None
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    background_color: str | None = None


class _AddLayerBody(BaseModel):
    name: str
    layer_type: str = "background"
    z_index: int | None = None


class _UpdateLayerBody(BaseModel):
    name: str | None = None
    x: float | None = None
    y: float | None = None
    scale: float | None = Field(default=None, gt=0)
    rotation: float | None = None
    opacity: float | None = None
    blend_mode: str | None = None
    visible: bool | None = None
    locked: bool | None = None


class _GenerateBody(BaseModel):
    action: str = "generate"
    model_id: str = "test-model"
    prompt: str = ""


def _err(status_code: int, code: str, detail: str = "") -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "detail": detail})


def _safe_detail(exc: Exception) -> str:
    raw = getattr(exc, "detail", str(exc))
    if "Traceback" in raw:
        return f"{getattr(exc, 'code', 'ERROR')}: request failed"
    return raw


def _map_exc(exc: Exception) -> JSONResponse:
    for exc_type, status in _ERROR_MAP.items():
        if isinstance(exc, exc_type):
            code = getattr(exc, "code", exc_type.__name__)
            return _err(status, code, _safe_detail(exc))
    raise exc


def make_canvas_router(store: Any, executor: Any, compositor: Any) -> APIRouter:
    router = APIRouter()

    async def _resolve_canvas(canvas_id: str, auth: AuthDep) -> CanvasRecord:
        canvas = await store.get_canvas(canvas_id)
        if canvas is None or canvas.org_id != auth.org_id:
            raise CanvasNotFoundError(f"canvas {canvas_id!r} not found")
        if canvas.is_archived():
            raise CanvasArchivedError(f"canvas {canvas_id!r} is archived")
        return canvas

    @router.post("/", status_code=201)
    async def create_canvas(body: _CreateCanvasBody, auth: AuthDep) -> Any:
        canvas = await store.create_canvas(
            name=body.name,
            width=body.width,
            height=body.height,
            background_color=body.background_color,
            org_id=auth.org_id,
        )
        return canvas.to_dict()

    @router.get("/")
    async def list_canvases(
        include_archived: bool = Query(default=False),
        auth: AuthDep = ...,  # type: ignore[assignment]
    ) -> Any:
        canvases = await store.list_canvases(auth.org_id, include_archived=include_archived)
        return [c.to_dict() for c in canvases]

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str, auth: AuthDep) -> Any:
        try:
            job = await store.get_job(job_id)
            if job is None:
                raise JobNotFoundError(f"job {job_id!r} not found")
            return job.to_dict()
        except Exception as exc:
            return _map_exc(exc)

    @router.post("/jobs/{job_id}/accept/{variant_index}")
    async def accept_variant(job_id: str, variant_index: int, auth: AuthDep) -> Any:
        try:
            job, layer = await executor.accept_variant(job_id, variant_index)
            return {"job": job.to_dict(), "layer": layer.to_dict()}
        except Exception as exc:
            return _map_exc(exc)

    @router.delete("/jobs/{job_id}")
    async def cancel_job(job_id: str, auth: AuthDep) -> Any:
        try:
            job = await executor.cancel_job(job_id)
            return job.to_dict()
        except Exception as exc:
            return _map_exc(exc)

    @router.get("/{canvas_id}")
    async def get_canvas(canvas_id: str, auth: AuthDep) -> Any:
        try:
            canvas = await _resolve_canvas(canvas_id, auth)
            return canvas.to_dict()
        except CanvasNotFoundError:
            return _err(404, "CANVAS_NOT_FOUND", f"canvas {canvas_id!r} not found")
        except CanvasArchivedError:
            return _err(410, "CANVAS_ARCHIVED", f"canvas {canvas_id!r} is archived")

    @router.patch("/{canvas_id}")
    async def update_canvas(canvas_id: str, body: _UpdateCanvasBody, auth: AuthDep) -> Any:
        try:
            canvas = await _resolve_canvas(canvas_id, auth)
            resizing = body.width is not None or body.height is not None
            if resizing and canvas.layer_count > 0:
                raise CanvasHasLayersError(f"canvas {canvas_id!r} has {canvas.layer_count} layers")
            if body.name is not None:
                canvas.name = body.name
            if body.width is not None:
                canvas.width = body.width
            if body.height is not None:
                canvas.height = body.height
            if body.background_color is not None:
                canvas.background_color = body.background_color
            canvas.updated_at = datetime.now(UTC)
            updated = await store.update_canvas(canvas)
            return updated.to_dict()
        except Exception as exc:
            return _map_exc(exc)

    @router.delete("/{canvas_id}")
    async def delete_canvas(canvas_id: str, auth: AuthDep) -> Any:
        try:
            canvas = await _resolve_canvas(canvas_id, auth)
            canvas.archived_at = datetime.now(UTC)
            canvas.updated_at = datetime.now(UTC)
            updated = await store.update_canvas(canvas)
            return updated.to_dict()
        except Exception as exc:
            return _map_exc(exc)

    @router.post("/{canvas_id}/layers", status_code=201)
    async def add_layer(canvas_id: str, body: _AddLayerBody, auth: AuthDep) -> Any:
        try:
            await _resolve_canvas(canvas_id, auth)
            kw: dict[str, Any] = {"name": body.name, "layer_type": body.layer_type}
            if body.z_index is not None:
                kw["z_index"] = body.z_index
            layer = await store.add_layer(canvas_id, **kw)
            return layer.to_dict()
        except Exception as exc:
            return _map_exc(exc)

    @router.patch("/{canvas_id}/layers/{layer_id}")
    async def update_layer(
        canvas_id: str, layer_id: str, body: _UpdateLayerBody, auth: AuthDep
    ) -> Any:
        try:
            await _resolve_canvas(canvas_id, auth)
            layer = await store.get_layer(layer_id)
            if layer is None or layer.canvas_id != canvas_id:
                raise LayerNotFoundError(f"layer {layer_id!r} not found")
            data = body.model_dump(exclude_none=True)
            if layer.locked:
                positional_keys = _POSITIONAL_FIELDS & data.keys()
                if positional_keys:
                    raise LayerLockedError(f"layer {layer_id!r} is locked")
            for key, val in data.items():
                if key == "rotation" and val is not None:
                    val = val % 360
                setattr(layer, key, val)
            layer.updated_at = datetime.now(UTC)
            updated = await store.update_layer(layer)
            return updated.to_dict()
        except Exception as exc:
            return _map_exc(exc)

    @router.delete("/{canvas_id}/layers/{layer_id}")
    async def delete_layer(canvas_id: str, layer_id: str, auth: AuthDep) -> Any:
        try:
            await _resolve_canvas(canvas_id, auth)
            layer = await store.get_layer(layer_id)
            if layer is None or layer.canvas_id != canvas_id:
                raise LayerNotFoundError(f"layer {layer_id!r} not found")
            await store.remove_layer(layer_id)
            return {"status": "ok"}
        except Exception as exc:
            return _map_exc(exc)

    @router.post("/{canvas_id}/layers/reorder")
    async def reorder_layers(
        canvas_id: str, assignments: list[dict[str, Any]], auth: AuthDep
    ) -> Any:
        try:
            await _resolve_canvas(canvas_id, auth)
            layers = await store.reorder_layers(canvas_id, assignments)
            return [layer.to_dict() for layer in layers]
        except Exception as exc:
            return _map_exc(exc)

    @router.post("/{canvas_id}/layers/{layer_id}/generate", status_code=202)
    async def generate(canvas_id: str, layer_id: str, body: _GenerateBody, auth: AuthDep) -> Any:
        try:
            await _resolve_canvas(canvas_id, auth)
            layer = await store.get_layer(layer_id)
            if layer is None or layer.canvas_id != canvas_id:
                raise LayerNotFoundError(f"layer {layer_id!r} not found")
            job = await executor.start_job(
                canvas_id=canvas_id,
                layer_id=layer_id,
                action=body.action,
                model_id=body.model_id,
                prompt=body.prompt,
            )
            return {"job_id": job.id, "status": job.status}
        except Exception as exc:
            return _map_exc(exc)

    @router.get("/{canvas_id}/export")
    async def export_canvas(
        canvas_id: str,
        fmt: str = Query(alias="format", default="png"),
        quality: int = Query(default=85, ge=1, le=100),
        auth: AuthDep = ...,  # type: ignore[assignment]
    ) -> Any:
        if fmt not in _SUPPORTED_FORMATS:
            return _err(400, "UNSUPPORTED_FORMAT", f"format {fmt!r} is not supported")
        try:
            canvas = await _resolve_canvas(canvas_id, auth)
            layers = await store.list_layers(canvas_id)
            composite_result = await compositor.composite(canvas, layers)
            image_bytes = composite_result.image_bytes
            if hasattr(compositor, "encode"):
                image_bytes = await compositor.encode(image_bytes, fmt, quality)
            content_types = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
            return Response(content=image_bytes, media_type=content_types[fmt])
        except CanvasNotFoundError:
            return _err(404, "CANVAS_NOT_FOUND", f"canvas {canvas_id!r} not found")
        except CanvasArchivedError:
            return _err(404, "CANVAS_NOT_FOUND", f"canvas {canvas_id!r} not found")
        except Exception as exc:
            return _map_exc(exc)

    return router
