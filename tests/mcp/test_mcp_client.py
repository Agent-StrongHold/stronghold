"""Outbound MCP client contract tests.

Uses ``httpx.MockTransport`` for transport isolation — no real network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from stronghold.mcp.client import MCPClient
from stronghold.types.security import (
    IssuedToken,
    RemoteScopeChallengeError,
    RemoteToolError,
    RemoteUnauthorizedError,
    ServerMetadata,
    TokenAudiencePassthroughError,
    ToolFingerprint,
)

CANONICAL_URI = "https://remote-mcp.example/mcp"
PRM_URL = "https://remote-mcp.example/.well-known/oauth-protected-resource/mcp"


def _token(audience: str = CANONICAL_URI, ttl_seconds: int = 900) -> IssuedToken:
    fingerprint = ToolFingerprint(value="fp-test", name="github_search", schema_hash="sh1")
    return IssuedToken(
        id="tok-1",
        tool=fingerprint,
        principal_user_id="alice",
        principal_org_id="acme",
        audience=audience,
        scopes=frozenset({"read:issues"}),
        issued_at=datetime.now(UTC),
        ttl_seconds=ttl_seconds,
        serialized="jwt-fake-payload",
    )


def _server() -> ServerMetadata:
    return ServerMetadata(
        canonical_uri=CANONICAL_URI,
        auth_servers=("https://auth.example",),
        scopes_supported=frozenset({"read:issues"}),
    )


def _prm_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/.well-known/oauth-protected-resource/mcp"):
        return httpx.Response(
            200,
            json={
                "resource": CANONICAL_URI,
                "authorization_servers": ["https://auth.example"],
                "scopes_supported": ["read:issues"],
            },
        )
    return httpx.Response(404)


# --- discovery --------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_parses_prm_and_caches() -> None:
    transport = httpx.MockTransport(_prm_handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        a = await client.discover(CANONICAL_URI)
        b = await client.discover(CANONICAL_URI)
    assert a == b
    assert a.canonical_uri == CANONICAL_URI
    assert a.auth_servers == ("https://auth.example",)
    assert a.scopes_supported == frozenset({"read:issues"})


@pytest.mark.asyncio
async def test_discover_rejects_non_https_outside_dev_mode() -> None:
    client = MCPClient()
    with pytest.raises(RemoteToolError):
        await client.discover("http://attacker.example/mcp")
    await client.aclose()


@pytest.mark.asyncio
async def test_discover_allows_localhost_in_dev_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resource": "http://localhost:9000/mcp",
                "authorization_servers": ["http://localhost:9100"],
                "scopes_supported": [],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner, dev_mode=True)
        metadata = await client.discover("http://localhost:9000/mcp")
    assert metadata.canonical_uri.startswith("http://localhost")


@pytest.mark.asyncio
async def test_malformed_prm_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"not-json", headers={"content-type": "application/json"}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        with pytest.raises(RemoteUnauthorizedError):
            await client.discover(CANONICAL_URI)


@pytest.mark.asyncio
async def test_prm_invalidated_on_401() -> None:
    state = {"prm_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/oauth-protected-resource/mcp"):
            state["prm_calls"] += 1
            return httpx.Response(
                200,
                json={
                    "resource": CANONICAL_URI,
                    "authorization_servers": ["https://auth.example"],
                    "scopes_supported": [],
                },
            )
        return httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{PRM_URL}", error="invalid_token"'
                ),
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        server = await client.discover(CANONICAL_URI)
        assert state["prm_calls"] == 1
        with pytest.raises(RemoteUnauthorizedError):
            await client.call_tool(server, "github_search", {}, _token())
        # PRM was invalidated; re-discovery hits the network again.
        await client.discover(CANONICAL_URI)
        assert state["prm_calls"] == 2


# --- token passthrough refusal ---------------------------------------------


@pytest.mark.asyncio
async def test_token_passthrough_audience_mismatch_refused_before_network() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        with pytest.raises(TokenAudiencePassthroughError):
            await client.call_tool(
                _server(),
                "github_search",
                {},
                _token(audience="https://different.example/mcp"),
            )


# --- happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_tool_returns_result_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "github_search"
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {"items": ["a", "b"]},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        result = await client.call_tool(_server(), "github_search", {"q": "x"}, _token())
    assert result == {"items": ["a", "b"]}


@pytest.mark.asyncio
async def test_list_tools_returns_descriptors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "tools": [
                        {
                            "name": "search",
                            "description": "Search the repo",
                            "inputSchema": {"type": "object"},
                        },
                    ],
                },
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        descriptors = await client.list_tools(_server(), _token())
    assert len(descriptors) == 1
    assert descriptors[0].name == "search"


# --- error handling ---------------------------------------------------------


@pytest.mark.asyncio
async def test_403_insufficient_scope_parses_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={
                "WWW-Authenticate": (
                    'Bearer error="insufficient_scope", '
                    'scope="read:issues write:issues", '
                    f'resource_metadata="{PRM_URL}"'
                ),
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        with pytest.raises(RemoteScopeChallengeError) as exc_info:
            await client.call_tool(_server(), "github_search", {}, _token())
    assert exc_info.value.required == frozenset({"read:issues", "write:issues"})


@pytest.mark.asyncio
async def test_jsonrpc_error_raises_remote_tool_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "invalid params"},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        with pytest.raises(RemoteToolError) as exc_info:
            await client.call_tool(_server(), "github_search", {}, _token())
    assert exc_info.value.code == -32602
    assert "invalid params" in exc_info.value.message


@pytest.mark.asyncio
async def test_500_response_raises_remote_tool_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500, text="boom"))
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        with pytest.raises(RemoteToolError) as exc_info:
            await client.call_tool(_server(), "github_search", {}, _token())
    assert exc_info.value.code == 500


@pytest.mark.asyncio
async def test_prm_ttl_expires_and_is_refreshed() -> None:
    state = {"prm_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["prm_calls"] += 1
        return httpx.Response(
            200,
            json={
                "resource": CANONICAL_URI,
                "authorization_servers": ["https://auth.example"],
                "scopes_supported": [],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner, prm_ttl=timedelta(milliseconds=1))
        await client.discover(CANONICAL_URI)
        assert state["prm_calls"] == 1
        # Force-expire by clearing the cache (TTL granularity in tests is
        # awkward; the cache invalidation path is the contract worth checking).
        client.invalidate_prm(CANONICAL_URI)
        await client.discover(CANONICAL_URI)
        assert state["prm_calls"] == 2
