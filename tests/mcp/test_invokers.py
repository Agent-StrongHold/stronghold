"""Backend invoker tests — REMOTE_PROXY and LOCAL_HOST."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from stronghold.mcp.client import MCPClient
from stronghold.mcp.emissary import (
    BackendRegistration,
    BackendUnavailableError,
)
from stronghold.mcp.invokers import make_local_host_invoker, make_remote_invoker
from stronghold.mcp.registry import MCPRegistry
from stronghold.mcp.types import (
    MCPServer,
    MCPServerSpec,
    MCPServerStatus,
    MCPSourceType,
)
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.security import (
    IssuedToken,
    MCPServerNotRunningError,
    RemoteToolError,
    TargetKind,
    ToolCallRequest,
    ToolFingerprint,
)

CANONICAL_URI = "https://remote-mcp.example/mcp"


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _fp(name: str = "github_search") -> ToolFingerprint:
    return ToolFingerprint(value=f"fp-{name}", name=name, schema_hash=f"sh-{name}")


def _token(audience: str) -> IssuedToken:
    return IssuedToken(
        id="tok-1",
        tool=_fp(),
        principal_user_id="alice",
        principal_org_id="acme",
        audience=audience,
        scopes=frozenset({"read"}),
        issued_at=datetime.now(UTC),
        ttl_seconds=900,
        serialized="jwt-fake",
    )


# --- REMOTE_PROXY -----------------------------------------------------------


@pytest.mark.asyncio
async def test_remote_invoker_dispatches_via_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/oauth-protected-resource/mcp"):
            return httpx.Response(
                200,
                json={
                    "resource": CANONICAL_URI,
                    "authorization_servers": ["https://auth.example"],
                    "scopes_supported": ["read"],
                },
            )
        body = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {"value": "remote-result"},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as inner:
        client = MCPClient(http=inner)
        invoker = make_remote_invoker(client)
        result = await invoker(
            BackendRegistration(
                fingerprint=_fp(),
                target_kind=TargetKind.REMOTE_PROXY,
                audiences=frozenset({CANONICAL_URI}),
                metadata={"server_uri": CANONICAL_URI},
            ),
            ToolCallRequest(
                fingerprint=_fp(),
                args={},
                auth=_alice(),
                call_id="c1",
            ),
            _token(CANONICAL_URI),
            None,
        )
    assert result == {"value": "remote-result"}


@pytest.mark.asyncio
async def test_remote_invoker_missing_server_uri_raises() -> None:
    async with httpx.AsyncClient() as inner:
        client = MCPClient(http=inner)
        invoker = make_remote_invoker(client)
        with pytest.raises(BackendUnavailableError):
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.REMOTE_PROXY,
                    audiences=frozenset({CANONICAL_URI}),
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token(CANONICAL_URI),
                None,
            )


# --- LOCAL_HOST -------------------------------------------------------------


def _registry_with(name: str, status: MCPServerStatus, endpoint: str = "") -> MCPRegistry:
    registry = MCPRegistry()
    server = MCPServer(
        spec=MCPServerSpec(
            name=name,
            image="ghcr.io/modelcontextprotocol/server-test:latest",
        ),
        source_type=MCPSourceType.MANAGED,
        status=status,
        endpoint=endpoint,
        org_id="acme",
    )
    registry._servers[name] = server  # direct insert; registry.register validates registries
    return registry


class _FakeDeployer:
    def __init__(self) -> None:
        self.health_calls = 0

    async def deploy_tool_mcp(self, tool_name: str, image: str) -> str:
        return f"deploy-{tool_name}"

    async def stop_tool_mcp(self, deployment_name: str) -> None:
        pass

    async def health(self) -> bool:
        self.health_calls += 1
        return True


@pytest.mark.asyncio
async def test_local_host_invoker_dispatches_to_endpoint() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        body = json.loads(request.content.decode())
        captured["method"] = body["method"]
        captured["params"] = body["params"]
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body.get("id"),
                "result": {"hit": True},
            },
        )

    registry = _registry_with(
        "github_search",
        MCPServerStatus.RUNNING,
        endpoint="http://github-mcp.svc:3000",
    )
    deployer = _FakeDeployer()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        result = await invoker(
            BackendRegistration(
                fingerprint=_fp(),
                target_kind=TargetKind.LOCAL_HOST,
                audiences=frozenset({"internal:github"}),
                metadata={"server_name": "github_search"},
            ),
            ToolCallRequest(
                fingerprint=_fp(),
                args={"q": "x"},
                auth=_alice(),
                call_id="c1",
            ),
            _token("internal:github"),
            None,
        )
    assert result == {"hit": True}
    assert captured["url"].endswith("/mcp")
    assert captured["auth"] == "Bearer jwt-fake"
    assert captured["method"] == "tools/call"
    assert captured["params"]["name"] == "github_search"


@pytest.mark.asyncio
async def test_local_host_invoker_pending_status_raises_not_running() -> None:
    registry = _registry_with(
        "github_search",
        MCPServerStatus.PENDING,
        endpoint="http://github-mcp.svc:3000",
    )
    deployer = _FakeDeployer()
    async with httpx.AsyncClient() as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        with pytest.raises(MCPServerNotRunningError) as exc_info:
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.LOCAL_HOST,
                    audiences=frozenset({"internal:github"}),
                    metadata={"server_name": "github_search"},
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token("internal:github"),
                None,
            )
    assert exc_info.value.status == "pending"


@pytest.mark.asyncio
async def test_local_host_invoker_failed_status_calls_health_then_raises() -> None:
    registry = _registry_with(
        "github_search",
        MCPServerStatus.FAILED,
        endpoint="http://github-mcp.svc:3000",
    )
    deployer = _FakeDeployer()
    async with httpx.AsyncClient() as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        with pytest.raises(MCPServerNotRunningError):
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.LOCAL_HOST,
                    audiences=frozenset({"internal:github"}),
                    metadata={"server_name": "github_search"},
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token("internal:github"),
                None,
            )
    assert deployer.health_calls == 1


@pytest.mark.asyncio
async def test_local_host_invoker_unregistered_server_raises() -> None:
    registry = MCPRegistry()
    deployer = _FakeDeployer()
    async with httpx.AsyncClient() as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        with pytest.raises(BackendUnavailableError):
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.LOCAL_HOST,
                    audiences=frozenset({"internal:github"}),
                    metadata={"server_name": "missing"},
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token("internal:github"),
                None,
            )


@pytest.mark.asyncio
async def test_local_host_invoker_missing_server_name_metadata_raises() -> None:
    registry = MCPRegistry()
    deployer = _FakeDeployer()
    async with httpx.AsyncClient() as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        with pytest.raises(BackendUnavailableError):
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.LOCAL_HOST,
                    audiences=frozenset({"internal:github"}),
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token("internal:github"),
                None,
            )


@pytest.mark.asyncio
async def test_local_host_invoker_500_endpoint_raises_backend_unavailable() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    registry = _registry_with(
        "github_search",
        MCPServerStatus.RUNNING,
        endpoint="http://github-mcp.svc:3000",
    )
    deployer = _FakeDeployer()
    async with httpx.AsyncClient(transport=transport) as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        with pytest.raises(BackendUnavailableError):
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.LOCAL_HOST,
                    audiences=frozenset({"internal:github"}),
                    metadata={"server_name": "github_search"},
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token("internal:github"),
                None,
            )


@pytest.mark.asyncio
async def test_local_host_invoker_jsonrpc_error_raises_remote_tool_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "bad args"},
            },
        )

    registry = _registry_with(
        "github_search",
        MCPServerStatus.RUNNING,
        endpoint="http://github-mcp.svc:3000",
    )
    deployer = _FakeDeployer()
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        invoker = make_local_host_invoker(deployer=deployer, registry=registry, http=http)
        with pytest.raises(RemoteToolError) as exc_info:
            await invoker(
                BackendRegistration(
                    fingerprint=_fp(),
                    target_kind=TargetKind.LOCAL_HOST,
                    audiences=frozenset({"internal:github"}),
                    metadata={"server_name": "github_search"},
                ),
                ToolCallRequest(fingerprint=_fp(), args={}, auth=_alice(), call_id="c1"),
                _token("internal:github"),
                None,
            )
    assert exc_info.value.code == -32602
