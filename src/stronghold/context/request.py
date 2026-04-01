"""Request context propagation via contextvars.

Each inbound HTTP request gets a ``RequestContext`` dataclass that carries
identifiers (request_id, user_id, org_id, session_id, trace_id) and
request-scoped settings (execution_mode, model_override).  The context is
stored in a ``contextvars.ContextVar`` so it propagates automatically
through ``async`` call chains without explicit parameter threading.

The ``request_context_middleware`` is a FastAPI/Starlette middleware that
creates the context from request headers at the start of a request and
resets it when the request completes.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

_request_context_var: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "stronghold_request_context",
    default=None,
)


def _make_request_id() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class RequestContext:
    """Per-request context that propagates through the call chain.

    Attributes:
        request_id: Unique identifier for this request (UUID4 by default).
        user_id: Authenticated user identifier.
        org_id: Organization (tenant) the user belongs to.
        session_id: Conversation session identifier.
        trace_id: Distributed tracing identifier.
        started_at: When the request started (UTC).
        execution_mode: How the request should be executed (e.g. best_effort, strict).
        model_override: Optional model to force for this request.
    """

    user_id: str
    org_id: str
    request_id: str = field(default_factory=_make_request_id)
    session_id: str = ""
    trace_id: str = ""
    started_at: datetime = field(default_factory=_utcnow)
    execution_mode: str = "best_effort"
    model_override: str | None = None


def get_request_context() -> RequestContext | None:
    """Return the current request context, or ``None`` if not set."""
    return _request_context_var.get()


def set_request_context(ctx: RequestContext) -> contextvars.Token[RequestContext | None]:
    """Store *ctx* as the current request context.

    Returns a token that can be passed to ``_request_context_var.reset()``
    to restore the previous value.
    """
    return _request_context_var.set(ctx)


async def request_context_middleware(
    request: Request,
    call_next: Callable[..., Any],
) -> Response:
    """FastAPI middleware that creates a ``RequestContext`` from request headers.

    Header mapping:
        X-Request-ID     -> request_id  (auto-generated UUID if missing)
        X-User-ID        -> user_id
        X-Org-ID         -> org_id
        X-Session-ID     -> session_id
        X-Trace-ID       -> trace_id
        X-Execution-Mode -> execution_mode  (defaults to "best_effort")
        X-Model-Override -> model_override
    """
    ctx = RequestContext(
        request_id=request.headers.get("x-request-id", "") or _make_request_id(),
        user_id=request.headers.get("x-user-id", ""),
        org_id=request.headers.get("x-org-id", ""),
        session_id=request.headers.get("x-session-id", ""),
        trace_id=request.headers.get("x-trace-id", ""),
        execution_mode=request.headers.get("x-execution-mode", "") or "best_effort",
        model_override=request.headers.get("x-model-override") or None,
    )

    token = set_request_context(ctx)
    try:
        response: Response = await call_next(request)
        return response
    finally:
        _request_context_var.reset(token)
