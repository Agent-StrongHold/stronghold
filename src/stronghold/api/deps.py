"""FastAPI dependency helpers.

Centralises shared request-scoped dependencies so routes can use
Depends(get_auth_context) and tests can override them cleanly via
app.dependency_overrides.
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request

from stronghold.types.auth import AuthContext


async def get_auth_context(request: Request) -> AuthContext:
    """Extract and validate the AuthContext from the incoming request.

    Delegates to the container's auth_provider so the actual
    authentication strategy (JWT, API key, etc.) is determined by the
    wired implementation.

    Raises HTTPException(401) when the request carries no valid credentials.
    """
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return cast(
            "AuthContext",
            await container.auth_provider.authenticate(
                auth_header,
                headers=dict(request.headers),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# Convenience type alias for route signatures
AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
