from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.admin")

router = APIRouter()

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

async def _require_admin(request: Request) -> Any:
    """Authenticate, require admin, then check CSRF on mutations."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Permission denied: admin role required")
    _check_csrf(request)
    return auth

@router.get("/v1/stronghold/admin/config")
async def get_config(request: Request) -> JSONResponse:
    """Return non-secret configuration values.

    Includes:
      - litellm_url: the configured LiteLLM proxy URL (no key)
      - auth_method: the configured auth method name
      - rate_limit: requests per minute setting
      - cors_origins: list of allowed origins
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    cfg = container.config

    # Build response, excluding any secret-like field
    response: dict[str, object] = {}
    if hasattr(cfg, "litellm_url") and cfg.litellm_url:
        response["litellm_url"] = cfg.litellm_url
    if hasattr(cfg, "auth_method") and cfg.auth_method:
        response["auth_method"] = cfg.auth_method
    if hasattr(cfg, "rate_limit") and cfg.rate_limit:
        response["rate_limit"] = str(cfg.rate_limit)
    if hasattr(cfg, "cors_origins") and cfg.cors_origins:
        response["cors_origins"] = cfg.cors_origins

    return JSONResponse(content=response)