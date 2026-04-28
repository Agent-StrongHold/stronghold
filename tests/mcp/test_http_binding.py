"""HTTP binding contract tests — MCP-spec compliance.

Exercises the Starlette ASGI app via httpx.ASGITransport (no real network).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from stronghold.mcp.composer import Composer
from stronghold.mcp.emissary import (
    BackendRegistration,
    Emissary,
)
from stronghold.mcp.http_binding import build_http_app
from stronghold.security.keyward import Keyward, KeywardConfig
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.security import (
    CatalogEntry,
    IncomingToken,
    Provenance,
    Scope,
    TargetKind,
    TokenAudienceMismatchError,
    TokenExpiredError,
    TokenValidationError,
    ToolFingerprint,
    TrustTier,
)

CANONICAL_URI = "https://emissary.test"
AUTH_SERVER = "https://auth.test"
SCOPES_SUPPORTED = frozenset({"read"})
SIGNING_KEY = "http-binding-test-signing-key-32-bytes-or-more"


# --- token validator fake ---------------------------------------------------


class _FakeTokenValidator:
    def __init__(self) -> None:
        self._tokens: dict[str, IncomingToken] = {}
        self._auths: dict[str, AuthContext] = {}

    def issue(
        self,
        raw: str,
        *,
        auth: AuthContext,
        audience: str = CANONICAL_URI,
        scopes: frozenset[str] = frozenset({"read"}),
        ttl_seconds: int = 900,
    ) -> str:
        self._tokens[raw] = IncomingToken(
            raw=raw,
            subject=auth.user_id,
            audience=audience,
            scopes=scopes,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        self._auths[raw] = auth
        return raw

    async def validate(self, raw_token: str, expected_audience: str) -> AuthContext:
        token = self._tokens.get(raw_token)
        if token is None:
            raise TokenValidationError("unknown token")
        if token.audience != expected_audience:
            raise TokenAudienceMismatchError(
                f"got {token.audience} want {expected_audience}",
            )
        if token.expires_at <= datetime.now(UTC):
            raise TokenExpiredError("expired")
        return self._auths[raw_token]


# --- fixtures ---------------------------------------------------------------


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        username="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _fp(name: str) -> ToolFingerprint:
    return ToolFingerprint(value=f"fp-{name}", name=name, schema_hash=f"sh-{name}")


def _approve(catalog: InMemoryToolCatalog, fingerprint: ToolFingerprint) -> None:
    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=TrustTier.T1,
            provenance=Provenance.ADMIN,
            approved_at_scope=Scope.ORG,
            org_id="acme",
            allowed_audiences=frozenset({"https://api.example/"}),
            declared_caps=frozenset({"read"}),
            approved_at=datetime.now(UTC),
            approved_by="admin",
        ),
    )


async def _local_invoker(
    registration: BackendRegistration,
    request,
    token,
    instance,
) -> dict[str, Any]:
    return {"ok": True, "tool": request.fingerprint.name, "args": request.args}


class _CleanWarden:
    async def scan(self, content: str, boundary: str):  # noqa: D401 - protocol shape
        from stronghold.types.security import WardenVerdict

        return WardenVerdict(clean=True)


def _build_app() -> tuple[Any, _FakeTokenValidator, InMemoryToolCatalog, Emissary]:
    catalog = InMemoryToolCatalog()
    keyward = Keyward(catalog=catalog, config=KeywardConfig(signing_key=SIGNING_KEY))
    composer = Composer()
    emissary = Emissary(
        catalog=catalog,
        keyward=keyward,
        warden=_CleanWarden(),  # type: ignore[arg-type]
        composer=composer,
        invokers={TargetKind.LOCAL_HOST: _local_invoker},
    )
    validator = _FakeTokenValidator()
    app = build_http_app(
        emissary=emissary,
        token_validator=validator,
        canonical_uri=CANONICAL_URI,
        auth_servers=(AUTH_SERVER,),
        scopes_supported=SCOPES_SUPPORTED,
    )
    return app, validator, catalog, emissary


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url=CANONICAL_URI)


# --- PRM --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prm_served_at_well_known_uri() -> None:
    app, *_ = _build_app()
    async with _client(app) as client:
        response = await client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == CANONICAL_URI
    assert AUTH_SERVER in body["authorization_servers"]
    assert "read" in body["scopes_supported"]


@pytest.mark.asyncio
async def test_prm_served_at_subpath() -> None:
    app, *_ = _build_app()
    async with _client(app) as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["resource"] == CANONICAL_URI


# --- 401 / WWW-Authenticate -------------------------------------------------


@pytest.mark.asyncio
async def test_unauthenticated_request_returns_401_with_prm_pointer() -> None:
    app, *_ = _build_app()
    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
    assert response.status_code == 401
    auth = response.headers.get("WWW-Authenticate", "")
    assert "Bearer" in auth
    assert "resource_metadata=" in auth
    assert "/.well-known/oauth-protected-resource" in auth


@pytest.mark.asyncio
async def test_token_with_wrong_audience_rejected_as_invalid() -> None:
    app, validator, *_ = _build_app()
    validator.issue("bad-aud", auth=_alice(), audience="https://other.example")
    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": "Bearer bad-aud"},
        )
    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["WWW-Authenticate"]


@pytest.mark.asyncio
async def test_unknown_token_rejected() -> None:
    app, *_ = _build_app()
    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": "Bearer not-a-token"},
        )
    assert response.status_code == 401


# --- happy-path RPC ---------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticated_tools_list_returns_authorized_set() -> None:
    app, validator, catalog, emissary = _build_app()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    emissary.register_backend(
        BackendRegistration(
            fingerprint=fingerprint,
            target_kind=TargetKind.LOCAL_HOST,
            audiences=frozenset({"https://api.example/"}),
        ),
    )
    validator.issue("alice-token", auth=_alice())

    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Authorization": "Bearer alice-token"},
        )

    assert response.status_code == 200
    body = response.json()
    names = [t["name"] for t in body["result"]["tools"]]
    assert "github_search" in names


@pytest.mark.asyncio
async def test_authenticated_tools_call_dispatches_to_emissary() -> None:
    app, validator, catalog, emissary = _build_app()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    emissary.register_backend(
        BackendRegistration(
            fingerprint=fingerprint,
            target_kind=TargetKind.LOCAL_HOST,
            audiences=frozenset({"https://api.example/"}),
        ),
    )
    validator.issue("alice-token", auth=_alice())

    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "github_search", "arguments": {"q": "bug"}},
            },
            headers={"Authorization": "Bearer alice-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 7
    assert body["result"]["isError"] is False
    assert body["result"]["content"]["tool"] == "github_search"


@pytest.mark.asyncio
async def test_unknown_tool_call_returns_jsonrpc_error_not_500() -> None:
    app, validator, *_ = _build_app()
    validator.issue("alice-token", auth=_alice())
    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "nope"},
            },
            headers={"Authorization": "Bearer alice-token"},
        )
    assert response.status_code == 200
    body = response.json()
    assert "error" in body
    assert "unknown" in body["error"]["message"]


@pytest.mark.asyncio
async def test_method_not_found_returns_jsonrpc_minus_32601() -> None:
    app, validator, *_ = _build_app()
    validator.issue("alice-token", auth=_alice())
    async with _client(app) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "completions/list"},
            headers={"Authorization": "Bearer alice-token"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["error"]["code"] == -32601
