"""Tests for OIDC auth provider with JWKS cache (Keycloak + Entra ID).

Uses real JWTs signed with an ephemeral RSA key. JWKS endpoint
is faked via respx so no external HTTP calls are made.
"""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import Response

from stronghold.security.auth_oidc import OIDCAuthProvider
from stronghold.security.jwks import JWKSCache
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.errors import AuthError, TokenExpiredError

# ── Fixtures: ephemeral RSA keypair + JWKS ──────────────────────────


def _generate_rsa_keypair() -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    """Generate an RSA private key and its JWK representation."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    public_numbers = public_key.public_numbers()

    # Encode as base64url integers (no padding)
    def _int_to_base64url(n: int, length: int) -> str:
        data = n.to_bytes(length, byteorder="big")
        import base64

        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    jwk: dict[str, Any] = {
        "kty": "RSA",
        "kid": "test-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": _int_to_base64url(public_numbers.n, 256),
        "e": _int_to_base64url(public_numbers.e, 3),
    }
    return private_key, jwk


_PRIVATE_KEY, _JWK = _generate_rsa_keypair()
_PRIVATE_KEY_2, _JWK_2 = _generate_rsa_keypair()
_JWK_2["kid"] = "test-key-2"

_JWKS_URL = "https://sso.example.com/.well-known/jwks.json"
_ISSUER = "https://sso.example.com"
_AUDIENCE = "stronghold-api"


def _jwks_response(*jwks: dict[str, Any]) -> Response:
    """Build a mock JWKS HTTP response."""
    body = {"keys": list(jwks)}
    return Response(200, json=body)


def _sign_token(
    claims: dict[str, Any],
    kid: str = "test-key-1",
    private_key: rsa.RSAPrivateKey | None = None,
) -> str:
    """Sign a JWT with the test RSA key."""
    key = private_key or _PRIVATE_KEY
    headers = {"kid": kid, "alg": "RS256"}
    return pyjwt.encode(claims, key, algorithm="RS256", headers=headers)


def _keycloak_claims(**overrides: Any) -> dict[str, Any]:
    """Standard Keycloak-style token claims."""
    claims: dict[str, Any] = {
        "sub": "user-kc-001",
        "preferred_username": "blake",
        "email": "blake@example.com",
        "realm_access": {"roles": ["admin", "user"]},
        "organization_id": "org-emerald",
        "team_id": "team-core",
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return claims


def _entra_claims(**overrides: Any) -> dict[str, Any]:
    """Standard Entra ID (Azure AD) style token claims."""
    claims: dict[str, Any] = {
        "sub": "user-entra-001",
        "preferred_username": "blake@contoso.com",
        "name": "Blake Matthews",
        "roles": ["GlobalAdmin", "Reader"],
        "tid": "tenant-contoso-123",
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
    }
    claims.update(overrides)
    return claims


# ── Keycloak claims mapping ─────────────────────────────────────────

_KEYCLOAK_CLAIMS_MAPPING: dict[str, str] = {
    "user_id": "sub",
    "username": "preferred_username",
    "roles": "realm_access.roles",
    "org_id": "organization_id",
    "team_id": "team_id",
}

# ── Entra ID claims mapping ─────────────────────────────────────────

_ENTRA_CLAIMS_MAPPING: dict[str, str] = {
    "user_id": "sub",
    "username": "preferred_username",
    "roles": "roles",
    "org_id": "tid",
    "team_id": "",
}


# ═══════════════════════════════════════════════════════════════════════
# JWKSCache tests
# ═══════════════════════════════════════════════════════════════════════


class TestJWKSCacheFetch:
    """JWKS key fetching and caching."""

    @respx.mock
    async def test_fetch_key_by_kid(self) -> None:
        """Cache fetches JWKS and returns the matching key."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        cache = JWKSCache(url=_JWKS_URL, ttl=3600.0)
        key = await cache.get_key("test-key-1")
        assert key is not None
        assert key["kid"] == "test-key-1"

    @respx.mock
    async def test_unknown_kid_returns_none(self) -> None:
        """Unknown kid returns None after refresh attempt."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        cache = JWKSCache(url=_JWKS_URL, ttl=3600.0)
        key = await cache.get_key("nonexistent-kid")
        assert key is None

    @respx.mock
    async def test_cache_reuses_keys(self) -> None:
        """Second call uses cached keys (no extra HTTP request)."""
        route = respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        cache = JWKSCache(url=_JWKS_URL, ttl=3600.0)
        await cache.get_key("test-key-1")
        await cache.get_key("test-key-1")
        assert route.call_count == 1

    @respx.mock
    async def test_refresh_forces_refetch(self) -> None:
        """Explicit refresh() bypasses TTL and refetches."""
        route = respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        cache = JWKSCache(url=_JWKS_URL, ttl=3600.0)
        await cache.get_key("test-key-1")
        assert route.call_count == 1
        await cache.refresh()
        assert route.call_count == 2

    @respx.mock
    async def test_unknown_kid_triggers_refresh_once(self) -> None:
        """Looking up an unknown kid triggers one refresh, then returns None."""
        route = respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        cache = JWKSCache(url=_JWKS_URL, ttl=3600.0)
        # First call: initial fetch
        await cache.get_key("test-key-1")
        assert route.call_count == 1
        # Second call with unknown kid: triggers refresh, still not found
        result = await cache.get_key("unknown-kid")
        assert result is None
        assert route.call_count == 2


# ═══════════════════════════════════════════════════════════════════════
# OIDCAuthProvider — Keycloak
# ═══════════════════════════════════════════════════════════════════════


class TestOIDCKeycloak:
    """OIDC auth with Keycloak-style claims."""

    @respx.mock
    async def test_valid_keycloak_token(self) -> None:
        """Full happy path: valid Keycloak JWT -> AuthContext."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        token = _sign_token(_keycloak_claims())
        ctx = await provider.authenticate(f"Bearer {token}")

        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == "user-kc-001"
        assert ctx.username == "blake"
        assert "admin" in ctx.roles
        assert "user" in ctx.roles
        assert ctx.org_id == "org-emerald"
        assert ctx.team_id == "team-core"
        assert ctx.auth_method == "oidc"
        assert ctx.kind == IdentityKind.USER

    @respx.mock
    async def test_keycloak_no_org_gives_empty(self) -> None:
        """Token without org_id claim -> empty org_id."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        claims = _keycloak_claims()
        del claims["organization_id"]
        del claims["team_id"]
        token = _sign_token(claims)
        ctx = await provider.authenticate(f"Bearer {token}")
        assert ctx.org_id == ""
        assert ctx.team_id == ""

    @respx.mock
    async def test_keycloak_no_roles_gives_empty(self) -> None:
        """Token without roles -> empty frozenset."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        claims = _keycloak_claims()
        del claims["realm_access"]
        token = _sign_token(claims)
        ctx = await provider.authenticate(f"Bearer {token}")
        assert ctx.roles == frozenset()


# ═══════════════════════════════════════════════════════════════════════
# OIDCAuthProvider — Entra ID
# ═══════════════════════════════════════════════════════════════════════


class TestOIDCEntraID:
    """OIDC auth with Entra ID (Azure AD) style claims."""

    @respx.mock
    async def test_valid_entra_token(self) -> None:
        """Full happy path: valid Entra ID JWT -> AuthContext."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_ENTRA_CLAIMS_MAPPING,
        )
        token = _sign_token(_entra_claims())
        ctx = await provider.authenticate(f"Bearer {token}")

        assert ctx.user_id == "user-entra-001"
        assert ctx.username == "blake@contoso.com"
        assert "GlobalAdmin" in ctx.roles
        assert "Reader" in ctx.roles
        assert ctx.org_id == "tenant-contoso-123"
        assert ctx.team_id == ""
        assert ctx.auth_method == "oidc"


# ═══════════════════════════════════════════════════════════════════════
# OIDCAuthProvider — role_mapping
# ═══════════════════════════════════════════════════════════════════════


class TestOIDCRoleMapping:
    """Role mapping translates IdP roles to Stronghold roles."""

    @respx.mock
    async def test_role_mapping_translates(self) -> None:
        """IdP roles are mapped to Stronghold roles via role_mapping."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_ENTRA_CLAIMS_MAPPING,
            role_mapping={"GlobalAdmin": "admin", "Reader": "viewer"},
        )
        token = _sign_token(_entra_claims())
        ctx = await provider.authenticate(f"Bearer {token}")
        assert ctx.roles == frozenset({"admin", "viewer"})

    @respx.mock
    async def test_unmapped_roles_are_kept(self) -> None:
        """Roles not in role_mapping are passed through unchanged."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
            role_mapping={"admin": "org_admin"},
        )
        token = _sign_token(_keycloak_claims())
        ctx = await provider.authenticate(f"Bearer {token}")
        # "admin" -> "org_admin", "user" stays as "user"
        assert "org_admin" in ctx.roles
        assert "user" in ctx.roles
        assert "admin" not in ctx.roles


# ═══════════════════════════════════════════════════════════════════════
# OIDCAuthProvider — error handling
# ═══════════════════════════════════════════════════════════════════════


class TestOIDCErrors:
    """Error cases for OIDC authentication."""

    async def test_missing_authorization_header(self) -> None:
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        with pytest.raises(AuthError, match="Missing Authorization"):
            await provider.authenticate(None)

    async def test_non_bearer_scheme(self) -> None:
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        with pytest.raises(AuthError, match="Invalid authorization format"):
            await provider.authenticate("Basic dXNlcjpwYXNz")

    async def test_empty_bearer_token(self) -> None:
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        with pytest.raises(AuthError, match="Empty token"):
            await provider.authenticate("Bearer ")

    @respx.mock
    async def test_expired_token(self) -> None:
        """Expired JWT raises TokenExpiredError."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        claims = _keycloak_claims(exp=int(time.time()) - 3600)
        token = _sign_token(claims)
        with pytest.raises(TokenExpiredError):
            await provider.authenticate(f"Bearer {token}")

    @respx.mock
    async def test_wrong_issuer(self) -> None:
        """JWT with wrong issuer is rejected."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        claims = _keycloak_claims(iss="https://evil.com")
        token = _sign_token(claims)
        with pytest.raises(AuthError, match="JWT validation failed"):
            await provider.authenticate(f"Bearer {token}")

    @respx.mock
    async def test_wrong_audience(self) -> None:
        """JWT with wrong audience is rejected."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        claims = _keycloak_claims(aud="wrong-audience")
        token = _sign_token(claims)
        with pytest.raises(AuthError, match="JWT validation failed"):
            await provider.authenticate(f"Bearer {token}")

    @respx.mock
    async def test_missing_sub_claim(self) -> None:
        """Token without sub claim is rejected."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        claims = _keycloak_claims()
        del claims["sub"]
        token = _sign_token(claims)
        with pytest.raises(AuthError, match="missing user_id"):
            await provider.authenticate(f"Bearer {token}")

    @respx.mock
    async def test_wrong_signing_key_rejected(self) -> None:
        """Token signed with a different key is rejected."""
        respx.get(_JWKS_URL).mock(return_value=_jwks_response(_JWK))
        provider = OIDCAuthProvider(
            issuer_url=_ISSUER,
            audience=_AUDIENCE,
            jwks_url=_JWKS_URL,
            claims_mapping=_KEYCLOAK_CLAIMS_MAPPING,
        )
        # Sign with key-2 but JWKS only has key-1
        token = _sign_token(_keycloak_claims(), kid="test-key-2", private_key=_PRIVATE_KEY_2)
        with pytest.raises(AuthError, match="JWT validation failed"):
            await provider.authenticate(f"Bearer {token}")
