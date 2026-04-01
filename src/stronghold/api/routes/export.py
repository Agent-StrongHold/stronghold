"""API route: export — GDPR Article 20 user data portability."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.export.user_data import UserDataExporter

logger = logging.getLogger("stronghold.api.export")

router = APIRouter()


async def _authenticate(request: Request) -> Any:
    """Authenticate request and return AuthContext."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role."""
    auth = await _authenticate(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


def _build_exporter(request: Request) -> UserDataExporter:
    """Build a UserDataExporter from the container's stores."""
    container = request.app.state.container
    return UserDataExporter(
        session_store=container.session_store,
        learning_store=container.learning_store,
        episodic_store=getattr(container, "episodic_store", None),
    )


@router.post("/v1/stronghold/export/me")
async def export_my_data(request: Request) -> JSONResponse:
    """Export all data for the authenticated user (GDPR Article 20)."""
    auth = await _authenticate(request)
    exporter = _build_exporter(request)
    result = await exporter.export_user(user_id=auth.user_id, org_id=auth.org_id)
    parsed = json.loads(result.to_json())
    logger.info(
        "Data export: user=%s org=%s records=%s",
        auth.user_id,
        auth.org_id,
        result.record_counts,
    )
    return JSONResponse(content=parsed)


@router.post("/v1/stronghold/export/user/{user_id}")
async def export_user_data(request: Request, user_id: str) -> JSONResponse:
    """Admin: export all data for a specific user (GDPR Article 20)."""
    auth = await _require_admin(request)
    exporter = _build_exporter(request)
    result = await exporter.export_user(user_id=user_id, org_id=auth.org_id)
    parsed = json.loads(result.to_json())
    logger.info(
        "Admin data export: target_user=%s admin=%s org=%s records=%s",
        user_id,
        auth.user_id,
        auth.org_id,
        result.record_counts,
    )
    return JSONResponse(content=parsed)
