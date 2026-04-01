"""API route: usage — per-user usage tracking and reporting.

GET /v1/stronghold/usage/me — returns UsageSummary for authenticated user
GET /v1/stronghold/usage/summary — admin-only aggregate by user
"""

from __future__ import annotations

import dataclasses
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

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


@router.get("/v1/stronghold/usage/me")
async def usage_me(request: Request, period: str = "") -> JSONResponse:
    """Get the current user's usage summary.

    Query params:
        period: optional, format "YYYY-MM", defaults to all-time if empty
    """
    auth = await _authenticate(request)
    container = request.app.state.container
    tracker = container.usage_tracker
    summary = await tracker.get_summary(
        user_id=auth.user_id,
        org_id=auth.org_id,
        period=period,
    )
    return JSONResponse(content=dataclasses.asdict(summary))


@router.get("/v1/stronghold/usage/summary")
async def usage_summary(request: Request, period: str = "") -> JSONResponse:
    """Admin-only: get aggregated usage for all users in the org.

    Query params:
        period: optional, format "YYYY-MM"
    """
    auth = await _authenticate(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")

    container = request.app.state.container
    tracker = container.usage_tracker
    summaries = await tracker.get_all_summaries(org_id=auth.org_id, period=period)
    return JSONResponse(
        content={"summaries": [dataclasses.asdict(s) for s in summaries]},
    )
