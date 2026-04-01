"""Password session authentication provider.

Validates HS256 JWTs signed with the router API key.
Used by the built-in login page (email + password).
Accepts tokens from two sources:
  1. Authorization header: "Bearer session-jwt:<token>" (injected by middleware)
  2. Session cookie (direct cookie reads, when headers are passed)

In production with OIDC configured, the JWTAuthProvider handles auth via RS256.
This provider handles the built-in password login flow.
"""

from __future__ import annotations

import logging
from http.cookies import SimpleCookie

import jwt as pyjwt

from stronghold.types.auth import AuthContext, IdentityKind

_PREFIX = "Bearer session-jwt:"
# Keep backward compat with existing sessions
_LEGACY_PREFIX = "Bearer demo-jwt:"

_MIN_KEY_LENGTH = 32
_logger = logging.getLogger("stronghold.auth.password")


class PasswordSessionAuthProvider:
    """Authenticates via HS256 JWT from the built-in login page.

    This provider uses symmetric HS256 signing with the router API key.
    In production, configure JWKS_URL to enable RS256 JWT auth (Keycloak,
    Entra ID, Auth0, Okta), which takes priority in the composite auth chain.
    """

    def __init__(self, api_key: str, cookie_name: str = "stronghold_session") -> None:
        if len(api_key) < _MIN_KEY_LENGTH:
            msg = (
                f"PasswordSessionAuthProvider: API key is {len(api_key)} bytes, "
                f"minimum required is {_MIN_KEY_LENGTH} for HS256 security. "
                f"Set a longer ROUTER_API_KEY."
            )
            raise ValueError(msg)
        self._key = api_key
        self._cookie_name = cookie_name

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        token: str = ""

        # Source 1: middleware-injected header (preferred — already validated format)
        if authorization:
            if authorization.startswith(_PREFIX):
                token = authorization[len(_PREFIX) :]
            elif authorization.startswith(_LEGACY_PREFIX):
                token = authorization[len(_LEGACY_PREFIX) :]

        # Source 2: direct cookie read
        if not token and headers:
            cookie_header = headers.get("cookie", "")
            if cookie_header:
                sc: SimpleCookie = SimpleCookie()
                try:
                    sc.load(cookie_header)
                except Exception:  # noqa: BLE001
                    pass
                else:
                    morsel = sc.get(self._cookie_name)
                    if morsel and morsel.value:
                        token = morsel.value

        if not token:
            msg = "No session token"
            raise ValueError(msg)

        try:
            claims = pyjwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience="stronghold",
                issuer="stronghold-demo",
            )
        except pyjwt.PyJWTError as e:
            msg = f"Invalid session: {e}"
            raise ValueError(msg) from e

        roles_raw = claims.get("roles", [])
        roles = frozenset(roles_raw) if isinstance(roles_raw, list) else frozenset()

        return AuthContext(
            user_id=claims.get("sub", ""),
            username=claims.get("preferred_username", ""),
            roles=roles,
            org_id=claims.get("organization_id", ""),
            team_id=claims.get("team_id", ""),
            kind=IdentityKind.USER,
            auth_method="password_session",
        )


# Backward-compatible alias
DemoCookieAuthProvider = PasswordSessionAuthProvider
