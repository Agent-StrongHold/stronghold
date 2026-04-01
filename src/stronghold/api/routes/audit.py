"""API route: audit — query, export, and stats for audit log entries."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from stronghold.audit.query import AuditQueryEngine

logger = logging.getLogger("stronghold.api.audit")

router = APIRouter()


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


def _parse_since(since: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime, or return None."""
    if not since:
        return None
    try:
        dt = datetime.fromisoformat(since)
        # Ensure timezone-aware (assume UTC if naive)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid 'since' timestamp: {since}. Use ISO 8601 format.",
        ) from e


@router.get("/v1/stronghold/audit")
async def query_audit(
    request: Request,
    org_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    boundary: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=10_000),
) -> JSONResponse:
    """Query audit log entries (admin-only, org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    engine = AuditQueryEngine(container.audit_log)

    # Use the auth org_id unless explicitly overridden (system admin only)
    effective_org_id = org_id if org_id is not None else auth.org_id

    entries = await engine.query(
        org_id=effective_org_id,
        user_id=user_id,
        boundary=boundary,
        since=_parse_since(since),
        limit=limit,
    )

    return JSONResponse(
        content=[
            {
                "timestamp": e.timestamp.isoformat(),
                "boundary": e.boundary,
                "user_id": e.user_id,
                "org_id": e.org_id,
                "team_id": e.team_id,
                "agent_id": e.agent_id,
                "tool_name": e.tool_name,
                "verdict": e.verdict,
                "trace_id": e.trace_id,
                "request_id": e.request_id,
                "detail": e.detail,
            }
            for e in entries
        ]
    )


@router.get("/v1/stronghold/audit/export")
async def export_audit_csv(
    request: Request,
    org_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    boundary: str | None = Query(default=None),
    since: str | None = Query(default=None),
    limit: int = Query(default=10_000, ge=1, le=100_000),
) -> Response:
    """Export audit log entries as CSV (admin-only)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    engine = AuditQueryEngine(container.audit_log)

    effective_org_id = org_id if org_id is not None else auth.org_id

    csv_data = await engine.export_csv(
        org_id=effective_org_id,
        user_id=user_id,
        boundary=boundary,
        since=_parse_since(since),
        limit=limit,
    )

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@router.get("/v1/stronghold/audit/stats")
async def audit_stats(
    request: Request,
    org_id: str | None = Query(default=None),
    since: str | None = Query(default=None),
) -> JSONResponse:
    """Aggregate audit log stats (admin-only): entries per boundary, per user, per hour."""
    auth = await _require_admin(request)
    container = request.app.state.container
    engine = AuditQueryEngine(container.audit_log)

    effective_org_id = org_id if org_id is not None else auth.org_id

    stats = await engine.stats(
        org_id=effective_org_id,
        since=_parse_since(since),
    )

    return JSONResponse(content=stats)
