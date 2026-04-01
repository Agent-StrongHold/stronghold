"""API route: memory — user-facing memory management (view, correct, forget)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated mutations."""
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return
    if not request.cookies:
        return
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


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
    _check_csrf(request)
    return auth, container


async def _require_admin(request: Request) -> tuple[Any, Any]:
    """Authenticate, require admin role, check CSRF."""
    auth, container = await _authenticate(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth, container


# ── GET routes ──────────────────────────────────────────────────────
# /me must come before /{memory_id} so "me" isn't captured as a path param.


@router.get("/v1/stronghold/memory/me")
async def list_my_memories(
    request: Request,
    limit: int = 20,
) -> JSONResponse:
    """List the caller's episodic memories."""
    auth, container = await _authenticate(request)
    mgr = container.memory_manager
    memories = await mgr.list_memories(
        user_id=auth.user_id,
        org_id=auth.org_id,
        limit=limit,
    )
    return JSONResponse(content={"memories": memories, "count": len(memories)})


@router.get("/v1/stronghold/memory/{memory_id}")
async def get_memory(memory_id: str, request: Request) -> JSONResponse:
    """Get a single memory by ID (org-scoped)."""
    auth, container = await _authenticate(request)
    mgr = container.memory_manager
    result = await mgr.get_memory(memory_id=memory_id, org_id=auth.org_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return JSONResponse(content=result)


# ── DELETE routes ───────────────────────────────────────────────────
# Fixed-path routes (/me, /user/{id}) MUST be registered before the
# parameterised /{memory_id} route so FastAPI doesn't swallow them.


@router.delete("/v1/stronghold/memory/me")
async def forget_by_keyword(
    request: Request,
    keyword: str = "",
) -> JSONResponse:
    """Bulk soft-delete memories matching a keyword (org-scoped)."""
    auth, container = await _authenticate(request)
    if not keyword:
        raise HTTPException(status_code=400, detail="'keyword' query parameter required")
    mgr = container.memory_manager
    count = await mgr.forget_by_keyword(
        user_id=auth.user_id,
        org_id=auth.org_id,
        keyword=keyword,
    )
    return JSONResponse(content={"status": "forgotten", "count": count, "keyword": keyword})


@router.delete("/v1/stronghold/memory/user/{user_id}")
async def purge_user_memories(user_id: str, request: Request) -> JSONResponse:
    """GDPR: purge all memories for a user (admin only, org-scoped)."""
    auth, container = await _require_admin(request)
    mgr = container.memory_manager
    count = await mgr.purge_user(user_id=user_id, org_id=auth.org_id)
    return JSONResponse(content={"status": "purged", "user_id": user_id, "count": count})


@router.put("/v1/stronghold/memory/{memory_id}")
async def correct_memory(memory_id: str, request: Request) -> JSONResponse:
    """Correct a memory's content (org-scoped)."""
    auth, container = await _authenticate(request)
    body = await request.json()
    new_content = body.get("content")
    if not new_content or not isinstance(new_content, str):
        raise HTTPException(status_code=400, detail="'content' field required (string)")
    mgr = container.memory_manager
    ok = await mgr.correct_memory(
        memory_id=memory_id,
        org_id=auth.org_id,
        new_content=new_content,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return JSONResponse(content={"status": "corrected", "memory_id": memory_id})


@router.delete("/v1/stronghold/memory/{memory_id}")
async def forget_memory(memory_id: str, request: Request) -> JSONResponse:
    """Soft-delete a single memory (org-scoped)."""
    auth, container = await _authenticate(request)
    mgr = container.memory_manager
    ok = await mgr.forget_memory(memory_id=memory_id, org_id=auth.org_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return JSONResponse(content={"status": "forgotten", "memory_id": memory_id})
