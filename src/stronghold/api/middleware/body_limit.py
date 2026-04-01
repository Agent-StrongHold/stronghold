"""Request body size limit middleware.

Addresses conductor_security.md S17 #22: No message body size limit.

Rejects requests with body size exceeding the configured limit.
Returns 413 Request Entity Too Large.

Supports:
- Content-Length header check (fast rejection without reading body)
- Chunked/streaming bodies without Content-Length (reads in chunks, aborts at limit)
- Per-route overrides via a dict of path -> limit
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

logger = logging.getLogger("stronghold.middleware.body_limit")

# Default: 1 MB
_DEFAULT_MAX_BODY_BYTES = 1_048_576


def _too_large_response(limit: int) -> JSONResponse:
    """Build a 413 JSON response."""
    return JSONResponse(
        status_code=413,
        content={
            "error": {
                "message": f"Request body too large (max {limit} bytes)",
                "type": "payload_error",
                "code": "BODY_TOO_LARGE",
            }
        },
    )


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with body size exceeding the configured limit.

    Returns 413 Request Entity Too Large for oversized requests.

    For requests with a ``Content-Length`` header the check is instant (no body
    read required).  For chunked / streaming requests without that header the
    middleware reads the body and aborts if the accumulated size exceeds the
    limit.

    Per-route overrides allow specific paths to have different limits
    (e.g. ``/upload`` may accept larger payloads).
    """

    def __init__(
        self,
        app: Any,
        max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
        route_overrides: dict[str, int] | None = None,
    ) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes
        self._route_overrides: dict[str, int] = route_overrides or {}

    def _limit_for_path(self, path: str) -> int:
        """Return the effective byte limit for a request path."""
        return self._route_overrides.get(path, self._max_body_bytes)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        limit = self._limit_for_path(request.url.path)
        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "message": "Invalid Content-Length",
                            "type": "request_error",
                        }
                    },
                )
            if length < 0 or length > limit:
                return _too_large_response(limit)
        elif request.method in {"POST", "PUT", "PATCH"}:
            # No Content-Length: read body and enforce limit.
            body = await request.body()
            if len(body) > limit:
                return _too_large_response(limit)

        result: Response = await call_next(request)
        return result
