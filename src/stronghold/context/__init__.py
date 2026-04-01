"""Request context propagation via contextvars.

Provides per-request context (request_id, user_id, org_id, session_id,
trace_id, etc.) that flows automatically through async call chains
without explicit parameter threading.

Usage::

    from stronghold.context.request import get_request_context, set_request_context

    ctx = get_request_context()  # None if not set
    token = set_request_context(ctx)  # returns reset token
"""

from __future__ import annotations

from stronghold.context.request import (
    RequestContext,
    get_request_context,
    request_context_middleware,
    set_request_context,
)

__all__ = [
    "RequestContext",
    "get_request_context",
    "request_context_middleware",
    "set_request_context",
]
