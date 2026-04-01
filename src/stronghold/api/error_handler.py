"""Standardized error response format with FastAPI exception handlers.

Provides a consistent JSON error envelope for all Stronghold API errors:
- StrongholdError hierarchy → mapped HTTP status codes
- Generic exceptions → sanitized 500 responses (no leaked internals)
- Optional request_id propagation from X-Request-ID header

Usage:
    from stronghold.api.error_handler import register_error_handlers
    app = FastAPI()
    register_error_handlers(app)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from stronghold.types.errors import (
    AuthError,
    ClassificationError,
    ConfigError,
    NoModelsError,
    PermissionDeniedError,
    QuotaExhaustedError,
    QuotaReserveError,
    RoutingError,
    SecurityError,
    SkillError,
    StrongholdError,
    ToolError,
)

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

logger = logging.getLogger("stronghold.api.error_handler")

# ── HTTP status mapping ──────────────────────────────────────────────
# Maps error classes to HTTP status codes. Order matters: check subclasses
# before parents so the most specific match wins.

_STATUS_MAP: list[tuple[type[StrongholdError], int]] = [
    # Auth subtypes
    (PermissionDeniedError, 403),
    # Auth base → 401
    (AuthError, 401),
    # Security hierarchy → 403
    (SecurityError, 403),
    # Routing subtypes
    (QuotaExhaustedError, 429),
    (QuotaReserveError, 429),
    (NoModelsError, 503),
    (RoutingError, 502),
    # Classification → 422 (unprocessable)
    (ClassificationError, 422),
    # Tool execution → 502 (upstream failure)
    (ToolError, 502),
    # Config / Skill → 500
    (ConfigError, 500),
    (SkillError, 500),
    # Base fallback
    (StrongholdError, 500),
]


def _status_for_error(exc: StrongholdError) -> int:
    """Resolve HTTP status code for a StrongholdError instance."""
    for err_cls, status in _STATUS_MAP:
        if isinstance(exc, err_cls):
            return status
    return 500  # pragma: no cover — unreachable with base fallback


# ── ErrorResponse dataclass ──────────────────────────────────────────


@dataclass
class ErrorResponse:
    """Standard JSON error envelope.

    Fields with None values are omitted from the serialized dict.
    """

    code: str
    message: str
    status: str = field(default="error", init=False)
    detail: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None fields."""
        d: dict[str, Any] = {
            "status": self.status,
            "code": self.code,
            "message": self.message,
        }
        if self.detail is not None:
            d["detail"] = self.detail
        if self.request_id is not None:
            d["request_id"] = self.request_id
        return d


# ── format_error ─────────────────────────────────────────────────────


def format_error(
    exc: Exception,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Convert any exception to a standard JSON error dict.

    StrongholdError instances expose their code and detail.
    Generic exceptions are sanitized to avoid leaking internals.
    """
    if isinstance(exc, StrongholdError):
        resp = ErrorResponse(
            code=exc.code,
            message=exc.detail,
            request_id=request_id,
        )
    else:
        resp = ErrorResponse(
            code="INTERNAL_ERROR",
            message="An internal error occurred",
            request_id=request_id,
        )
    return resp.to_dict()


# ── FastAPI exception handlers ───────────────────────────────────────


def _extract_request_id(request: Request) -> str | None:
    """Extract X-Request-ID header if present."""
    return request.headers.get("x-request-id")


async def stronghold_exception_handler(
    request: Request,
    exc: StrongholdError,
) -> JSONResponse:
    """Handle all StrongholdError subclasses with appropriate HTTP status."""
    request_id = _extract_request_id(request)
    status_code = _status_for_error(exc)
    body = format_error(exc, request_id=request_id)

    logger.warning(
        "StrongholdError [%s] %s (status=%d, request_id=%s)",
        exc.code,
        exc.detail,
        status_code,
        request_id,
    )

    return JSONResponse(status_code=status_code, content=body)


async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Catch-all handler that sanitizes stack traces.

    ValueError is treated as a validation error (400).
    Everything else becomes a sanitized 500.
    """
    request_id = _extract_request_id(request)

    if isinstance(exc, ValueError):
        body = ErrorResponse(
            code="VALIDATION_ERROR",
            message=str(exc),
            request_id=request_id,
        ).to_dict()
        status_code = 400
    else:
        logger.exception(
            "Unhandled exception (request_id=%s): %s",
            request_id,
            type(exc).__name__,
        )
        body = format_error(exc, request_id=request_id)
        status_code = 500

    return JSONResponse(status_code=status_code, content=body)


# ── Registration ─────────────────────────────────────────────────────


def register_error_handlers(app: FastAPI) -> None:
    """Register both exception handlers on a FastAPI application."""
    app.add_exception_handler(StrongholdError, stronghold_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, generic_exception_handler)
