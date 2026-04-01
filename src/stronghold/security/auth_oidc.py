"""OIDC authentication provider — configurable for Keycloak, Entra ID, and any OIDC IdP.

Validates RS256 JWTs against a JWKS endpoint, extracts user identity
via configurable claims_mapping, and optionally translates IdP roles
to Stronghold roles via role_mapping.

Usage:
    # Keycloak
    provider = OIDCAuthProvider(
        issuer_url="https://sso.example.com/realms/stronghold",
        audience="stronghold-api",
        jwks_url="https://sso.example.com/realms/stronghold/protocol/openid-connect/certs",
        claims_mapping={
            "user_id": "sub",
            "username": "preferred_username",
            "roles": "realm_access.roles",
            "org_id": "organization_id",
            "team_id": "team_id",
        },
    )

    # Entra ID
    provider = OIDCAuthProvider(
        issuer_url="https://login.microsoftonline.com/{tenant}/v2.0",
        audience="api://stronghold",
        jwks_url="https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
        claims_mapping={
            "user_id": "sub",
            "username": "preferred_username",
            "roles": "roles",
            "org_id": "tid",
            "team_id": "",
        },
        role_mapping={"GlobalAdmin": "admin", "Reader": "viewer"},
    )
"""

from __future__ import annotations

import logging
from typing import Any

import jwt as pyjwt
from jwt.exceptions import ExpiredSignatureError

from stronghold.security.jwks import JWKSCache
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.errors import AuthError, TokenExpiredError

logger = logging.getLogger("stronghold.security.auth_oidc")


class OIDCAuthProvider:
    """Authenticates requests via OIDC JWT tokens.

    Implements the AuthProvider protocol.

    Args:
        issuer_url: Expected ``iss`` claim value.
        audience: Expected ``aud`` claim value.
        jwks_url: URL to the JWKS endpoint for signature verification.
        claims_mapping: Maps Stronghold fields to JWT claim paths.
            Required keys: ``user_id``, ``username``, ``roles``.
            Optional keys: ``org_id``, ``team_id``.
            Values use dot-notation for nested claims (e.g., ``realm_access.roles``).
            Empty string means "not mapped" (field defaults to empty).
        role_mapping: Optional dict mapping IdP role names to Stronghold role names.
            Unmapped roles are passed through unchanged.
        jwks_ttl: TTL for the JWKS cache in seconds (default: 3600).
        algorithms: Allowed JWT signing algorithms (default: RS256).
    """

    def __init__(
        self,
        issuer_url: str,
        audience: str,
        jwks_url: str,
        claims_mapping: dict[str, str],
        role_mapping: dict[str, str] | None = None,
        jwks_ttl: float = 3600.0,
        algorithms: list[str] | None = None,
    ) -> None:
        self._issuer = issuer_url
        self._audience = audience
        self._claims_mapping = claims_mapping
        self._role_mapping = role_mapping or {}
        self._algorithms = algorithms or ["RS256"]
        self._jwks_cache = JWKSCache(url=jwks_url, ttl=jwks_ttl)

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> AuthContext:
        """Validate an OIDC JWT and return an AuthContext.

        Raises AuthError (or TokenExpiredError) on failure.
        """
        token = self._extract_bearer_token(authorization)
        claims = await self._decode_and_validate(token)

        # Extract identity fields via claims_mapping
        user_id = self._extract_claim(claims, "user_id")
        username = self._extract_claim(claims, "username") or user_id
        raw_roles = self._extract_claim_value(claims, "roles")
        org_id = self._extract_claim(claims, "org_id")
        team_id = self._extract_claim(claims, "team_id")

        if not user_id:
            raise AuthError(
                "Token missing user_id claim (mapped from "
                f"'{self._claims_mapping.get('user_id', 'sub')}')"
            )

        # Normalize roles to list
        roles_list: list[str]
        if isinstance(raw_roles, list):
            roles_list = [str(r) for r in raw_roles]
        elif isinstance(raw_roles, str):
            roles_list = [raw_roles]
        else:
            roles_list = []

        # Apply role mapping
        if self._role_mapping:
            roles_list = [self._role_mapping.get(r, r) for r in roles_list]

        return AuthContext(
            user_id=str(user_id),
            username=str(username),
            roles=frozenset(roles_list),
            org_id=str(org_id) if org_id else "",
            team_id=str(team_id) if team_id else "",
            kind=IdentityKind.USER,
            auth_method="oidc",
        )

    # ── Private helpers ─────────────────────────────────────────────

    @staticmethod
    def _extract_bearer_token(authorization: str | None) -> str:
        """Extract and validate the Bearer token from the Authorization header."""
        if not authorization:
            raise AuthError("Missing Authorization header")
        if not authorization.startswith("Bearer "):
            raise AuthError("Invalid authorization format (expected 'Bearer <token>')")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AuthError("Empty token")
        return token

    async def _decode_and_validate(self, token: str) -> dict[str, Any]:
        """Decode JWT, verify signature against JWKS, validate exp/iss/aud."""
        # Extract kid from unverified header
        try:
            unverified_header = pyjwt.get_unverified_header(token)
        except pyjwt.exceptions.DecodeError as e:
            raise AuthError(f"JWT validation failed: malformed token ({e})") from e

        kid = unverified_header.get("kid", "")
        if not kid:
            raise AuthError("JWT validation failed: missing kid in header")

        # Fetch the signing key from JWKS
        jwk_data = await self._jwks_cache.get_key(kid)
        if jwk_data is None:
            raise AuthError(f"JWT validation failed: unknown signing key (kid={kid})")

        # Build a PyJWK from the raw JWK dict
        try:
            signing_key = pyjwt.PyJWK(jwk_data)
        except Exception as e:
            raise AuthError(f"JWT validation failed: invalid JWK ({e})") from e

        # Decode and validate
        try:
            decoded: dict[str, Any] = pyjwt.decode(
                token,
                signing_key,
                algorithms=self._algorithms,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "aud"]},
            )
        except ExpiredSignatureError as e:
            raise TokenExpiredError("Token has expired") from e
        except pyjwt.exceptions.PyJWTError as e:
            raise AuthError(f"JWT validation failed: {e}") from e

        return decoded

    def _extract_claim(self, claims: dict[str, Any], field: str) -> str:
        """Extract a single string claim via the claims_mapping."""
        value = self._extract_claim_value(claims, field)
        if value is None:
            return ""
        return str(value)

    def _extract_claim_value(self, claims: dict[str, Any], field: str) -> Any:
        """Extract a claim value (any type) via the claims_mapping."""
        path = self._claims_mapping.get(field, "")
        if not path:
            return None
        return self._extract_nested(claims, path)

    @staticmethod
    def _extract_nested(claims: dict[str, Any], path: str) -> Any:
        """Extract a nested value using dot-notation path.

        Example: "realm_access.roles" -> claims["realm_access"]["roles"]

        Handles URL-style claim names (e.g., "https://myapp.com/roles")
        by checking exact match first.
        """
        if not path:
            return None

        # Exact match first (handles URL-style claim names)
        if path in claims:
            return claims[path]

        # Dot-notation traversal
        current: Any = claims
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
