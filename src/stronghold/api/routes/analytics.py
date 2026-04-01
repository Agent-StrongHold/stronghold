"""API routes: cost analytics and chargeback reporting."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("stronghold.api.analytics")

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


@router.get("/v1/stronghold/analytics/costs")
async def get_cost_summary(request: Request) -> JSONResponse:
    """Admin-only, org-scoped cost summary.

    Query params:
        period: str — e.g. "2025-03" (YYYY-MM)
        group_by: str — user|team|model|task_type (default: user)
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    tracker = container.cost_tracker
    period = request.query_params.get("period", "")
    group_by = request.query_params.get("group_by", "user")

    summary = await tracker.get_summary(org_id=auth.org_id, period=period, group_by=group_by)
    return JSONResponse(
        content={
            "period": summary.period,
            "org_id": summary.org_id,
            "total_cost_usd": summary.total_cost_usd,
            "total_tokens": summary.total_tokens,
            "total_requests": summary.total_requests,
            "by_user": summary.by_user,
            "by_team": summary.by_team,
            "by_model": summary.by_model,
            "by_task_type": summary.by_task_type,
        }
    )


@router.get("/v1/stronghold/analytics/costs/export")
async def export_costs_csv(request: Request) -> PlainTextResponse:
    """CSV download of cost records (admin-only, org-scoped).

    Query params:
        period: str — e.g. "2025-03" (YYYY-MM)
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    tracker = container.cost_tracker
    period = request.query_params.get("period", "")

    csv_str = await tracker.export_csv(org_id=auth.org_id, period=period)
    return PlainTextResponse(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=costs.csv"},
    )


@router.get("/v1/stronghold/analytics/suggestions")
async def get_optimization_suggestions(request: Request) -> JSONResponse:
    """Cost optimization suggestions (admin-only, org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    tracker = container.cost_tracker

    suggestions = await tracker.get_optimization_suggestions(org_id=auth.org_id)
    return JSONResponse(content=suggestions)
