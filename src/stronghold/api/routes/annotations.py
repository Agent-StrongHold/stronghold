"""API routes: annotations — tag, rate, and annotate conversations."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from stronghold.types.annotation import Annotation

logger = logging.getLogger("stronghold.api.annotations")

router = APIRouter()


async def _authenticate(request: Request) -> tuple[Any, Any]:
    """Authenticate and return (auth, container)."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return auth, container


def _serialize(ann: Annotation) -> dict[str, Any]:
    """Serialize an Annotation to a JSON-safe dict."""
    return {
        "id": ann.id,
        "session_id": ann.session_id,
        "user_id": ann.user_id,
        "org_id": ann.org_id,
        "tags": ann.tags,
        "rating": ann.rating,
        "note": ann.note,
        "created_at": ann.created_at.isoformat(),
    }


@router.post("/v1/stronghold/annotations")
async def create_annotation(request: Request) -> JSONResponse:
    """Create a new annotation on a conversation session."""
    auth, container = await _authenticate(request)
    body = await request.json()

    annotation = Annotation(
        session_id=body.get("session_id", ""),
        user_id=auth.user_id,
        org_id=auth.org_id,
        tags=body.get("tags", []),
        rating=body.get("rating"),
        note=body.get("note", ""),
    )

    try:
        result = await container.annotation_store.annotate(annotation)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return JSONResponse(content=_serialize(result))


@router.get("/v1/stronghold/annotations/{session_id}")
async def get_session_annotations(session_id: str, request: Request) -> JSONResponse:
    """Get all annotations for a session, scoped to caller's org."""
    auth, container = await _authenticate(request)
    annotations = await container.annotation_store.get_annotations(session_id, org_id=auth.org_id)
    return JSONResponse(content=[_serialize(a) for a in annotations])


@router.get("/v1/stronghold/annotations")
async def list_annotations(
    request: Request,
    tag: str | None = Query(default=None, description="Filter by tag"),
    rating_below: int | None = Query(default=None, description="Filter by max rating"),
) -> JSONResponse:
    """List annotations filtered by tag or rating, scoped to caller's org."""
    auth, container = await _authenticate(request)

    if tag is not None:
        results = await container.annotation_store.list_by_tag(tag, org_id=auth.org_id)
        return JSONResponse(content=[_serialize(a) for a in results])

    if rating_below is not None:
        results = await container.annotation_store.list_by_rating(rating_below, org_id=auth.org_id)
        return JSONResponse(content=[_serialize(a) for a in results])

    # No filter — return empty (could add list-all in the future)
    return JSONResponse(content=[])


@router.delete("/v1/stronghold/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, request: Request) -> JSONResponse:
    """Delete an annotation by ID, scoped to caller's org."""
    auth, container = await _authenticate(request)
    deleted = await container.annotation_store.delete_annotation(annotation_id, org_id=auth.org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return JSONResponse(content={"deleted": True, "annotation_id": annotation_id})
