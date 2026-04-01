"""API routes: human escalation management."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.escalations")

router = APIRouter()


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated mutations."""
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return  # Bearer token — not CSRF-vulnerable
    if not request.cookies:
        return  # No cookies = not a browser session
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


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
    _check_csrf(request)
    return auth


@router.get("/v1/stronghold/escalations")
async def list_escalations(request: Request) -> JSONResponse:
    """List pending escalations (admin only, org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    manager = container.escalation_manager
    pending = await manager.list_pending(org_id=auth.org_id)
    return JSONResponse(
        content=[
            {
                "id": esc.id,
                "session_id": esc.session_id,
                "agent_name": esc.agent_name,
                "user_id": esc.user_id,
                "reason": esc.reason,
                "status": esc.status,
                "created_at": esc.created_at,
            }
            for esc in pending
        ]
    )


@router.get("/v1/stronghold/escalations/{esc_id}")
async def get_escalation(request: Request, esc_id: str) -> JSONResponse:
    """Get escalation details (admin only, org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    manager = container.escalation_manager
    esc = await manager.get(esc_id, org_id=auth.org_id)
    if esc is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return JSONResponse(
        content={
            "id": esc.id,
            "session_id": esc.session_id,
            "agent_name": esc.agent_name,
            "user_id": esc.user_id,
            "org_id": esc.org_id,
            "reason": esc.reason,
            "context": esc.context,
            "status": esc.status,
            "response": esc.response,
            "created_at": esc.created_at,
            "resolved_at": esc.resolved_at,
            "resolved_by": esc.resolved_by,
        }
    )


@router.post("/v1/stronghold/escalations/{esc_id}/respond")
async def respond_escalation(request: Request, esc_id: str) -> JSONResponse:
    """Human responds to an escalation (admin only)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    manager = container.escalation_manager
    body = await request.json()
    response_text: str = body.get("response", "")
    if not response_text:
        raise HTTPException(status_code=400, detail="response is required")
    ok = await manager.respond(
        esc_id,
        org_id=auth.org_id,
        response=response_text,
        resolved_by=auth.user_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found or already resolved")
    return JSONResponse(content={"status": "responded"})


@router.post("/v1/stronghold/escalations/{esc_id}/takeover")
async def takeover_escalation(request: Request, esc_id: str) -> JSONResponse:
    """Human takes over the session (admin only)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    manager = container.escalation_manager
    ok = await manager.takeover(
        esc_id,
        org_id=auth.org_id,
        resolved_by=auth.user_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found or already resolved")
    return JSONResponse(content={"status": "taken_over"})


@router.post("/v1/stronghold/escalations/{esc_id}/dismiss")
async def dismiss_escalation(request: Request, esc_id: str) -> JSONResponse:
    """Dismiss an escalation — agent retries (admin only)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    manager = container.escalation_manager
    ok = await manager.dismiss(
        esc_id,
        org_id=auth.org_id,
        resolved_by=auth.user_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Escalation not found or already resolved")
    return JSONResponse(content={"status": "dismissed"})
