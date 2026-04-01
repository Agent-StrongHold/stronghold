"""API route: sessions — view and manage conversation history."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from stronghold.sessions.store import validate_session_ownership

router = APIRouter()

# Session IDs must be alphanumeric with / : - _ (no path traversal)
_SESSION_ID_PATTERN = re.compile(r"^[\w/:\-]+$")


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated mutations.

    CSRF only applies when auth is via cookies (browser session).
    Bearer token auth and unauthenticated requests are not CSRF-vulnerable.
    """
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return  # Bearer token — not CSRF-vulnerable
    # Only enforce CSRF when a session cookie is present (browser auth)
    if not request.cookies:
        return  # No cookies = not a browser session, auth will reject
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


async def _authenticate(request: Request) -> tuple[Any, Any]:
    """Authenticate and return (auth, container). CSRF checked after auth."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    _check_csrf(request)
    return auth, container


def _validate_session_id(session_id: str) -> None:
    """Validate session ID format to prevent path traversal."""
    if not _SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")


@router.get("/v1/stronghold/sessions")
async def list_sessions(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """List conversations for the authenticated user, sorted by recency."""
    auth, container = await _authenticate(request)
    store = container.session_store

    sessions = await store.list_sessions(
        user_id=auth.user_id, org_id=auth.org_id, limit=limit, offset=offset
    )
    return JSONResponse(content=sessions)


@router.get("/v1/stronghold/sessions/search")
async def search_sessions(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    """Search conversation content for the authenticated user."""
    auth, container = await _authenticate(request)
    store = container.session_store

    results = await store.search_sessions(
        user_id=auth.user_id, org_id=auth.org_id, query=q, limit=limit
    )
    return JSONResponse(content=results)


@router.get("/v1/stronghold/sessions/{session_id:path}")
async def get_session(session_id: str, request: Request) -> JSONResponse:
    """Get conversation history for a session (org-scoped)."""
    _validate_session_id(session_id)
    auth, container = await _authenticate(request)

    # Org isolation: reject if session doesn't belong to caller's org
    if not validate_session_ownership(session_id, auth.org_id):
        raise HTTPException(status_code=404, detail="Session not found")

    history = await container.session_store.get_history(session_id)
    return JSONResponse(content={"session_id": session_id, "messages": history})


@router.delete("/v1/stronghold/sessions/{session_id:path}")
async def delete_session(session_id: str, request: Request) -> JSONResponse:
    """Delete a session (org-scoped)."""
    _validate_session_id(session_id)
    auth, container = await _authenticate(request)

    # Org isolation: reject if session doesn't belong to caller's org
    if not validate_session_ownership(session_id, auth.org_id):
        raise HTTPException(status_code=404, detail="Session not found")

    await container.session_store.delete_session(session_id)
    return JSONResponse(content={"status": "deleted", "session_id": session_id})
