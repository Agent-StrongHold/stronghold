"""API route: conductor."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext


@dataclass(slots=True)
class RequestContext:
    """Per-request context propagated via contextvars."""

    request_id: str
    tenant: str | None
    user: str | None
    auth: AuthContext | None
    metadata: dict[str, Any] | None = None


request_context_var: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)

router = APIRouter(prefix="/v1/stronghold", tags=["conductor"])


@router.post("/conductor")
async def conductor_endpoint(request: Request) -> dict[str, Any]:
    """Conductor endpoint that sets request context."""
    json_data = await request.json()
    metadata = json_data.get("metadata", {})
    request_id = metadata.get("request_id", "unknown")

    # Create and set the request context
    ctx = RequestContext(
        request_id=request_id,
        tenant=metadata.get("tenant"),
        user=metadata.get("user"),
        auth=metadata.get("auth"),
        metadata=metadata,
    )
    token = request_context_var.set(ctx)

    try:
        # TODO: Actual conductor logic will go here
        return {"status": "ok", "request_id": request_id}
    finally:
        request_context_var.reset(token)
