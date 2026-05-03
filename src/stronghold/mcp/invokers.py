"""Backend invokers for Emissary's TargetKinds.

Each invoker is a small adapter from Emissary's ``BackendInvoker`` callable
shape to the production transport for a given target kind. The invokers
stay outside ``Emissary`` itself so the gateway core has no transport
concerns.

- ``make_remote_invoker``: wraps :class:`stronghold.mcp.client.MCPClient`
  for ``TargetKind.REMOTE_PROXY``.
- ``make_local_host_invoker``: wraps the existing ``MCPDeployer`` +
  ``MCPRegistry`` for ``TargetKind.LOCAL_HOST`` — looks up the deployed
  pod's endpoint and dispatches a JSON-RPC ``tools/call`` against it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from stronghold.mcp.emissary import BackendUnavailableError
from stronghold.mcp.types import MCPServerStatus
from stronghold.types.security import (
    MCPServerNotRunningError,
    RemoteToolError,
)

if TYPE_CHECKING:
    from stronghold.mcp.client import MCPClient
    from stronghold.mcp.emissary import BackendInvoker, BackendRegistration
    from stronghold.mcp.registry import MCPRegistry
    from stronghold.protocols.mcp import McpDeployerClient
    from stronghold.types.security import IssuedToken, ToolCallRequest


def make_remote_invoker(client: MCPClient) -> BackendInvoker:
    """Adapter: ``REMOTE_PROXY`` → ``MCPClient.call_tool``.

    ``BackendRegistration.metadata['server_uri']`` is the canonical URI.
    """

    async def invoke(
        registration: BackendRegistration,
        request: ToolCallRequest,
        token: IssuedToken,
        instance: str | None,
    ) -> dict[str, Any]:
        del instance  # session affinity is irrelevant for stateless proxy
        server_uri = registration.metadata.get("server_uri")
        if not server_uri:
            raise BackendUnavailableError(
                f"REMOTE_PROXY {request.fingerprint.name} missing server_uri",
            )
        server = await client.discover(server_uri)
        return await client.call_tool(
            server=server,
            tool_name=request.fingerprint.name,
            args=request.args,
            token=token,
        )

    return invoke


def make_local_host_invoker(
    *,
    deployer: McpDeployerClient,
    registry: MCPRegistry,
    http: httpx.AsyncClient,
) -> BackendInvoker:
    """Adapter: ``LOCAL_HOST`` → JSON-RPC against the deployed pod's endpoint.

    ``BackendRegistration.metadata['server_name']`` keys the ``MCPRegistry``.
    Refuses if status is not RUNNING; triggers a ``deployer.health()`` call
    on FAILED status so the diagnostic is recorded in the deployer's audit
    surface.
    """

    async def invoke(
        registration: BackendRegistration,
        request: ToolCallRequest,
        token: IssuedToken,
        instance: str | None,
    ) -> dict[str, Any]:
        del instance
        server_name = registration.metadata.get("server_name")
        if not server_name:
            raise BackendUnavailableError(
                f"LOCAL_HOST {request.fingerprint.name} missing server_name",
            )

        server = registry.get(server_name)
        if server is None:
            raise BackendUnavailableError(
                f"LOCAL_HOST {server_name!r} not registered",
            )

        if server.status is MCPServerStatus.FAILED:
            await deployer.health()  # diagnostic; result not consumed here
            raise MCPServerNotRunningError(server_name, server.status.value)
        if server.status is not MCPServerStatus.RUNNING:
            raise MCPServerNotRunningError(server_name, server.status.value)

        if not server.endpoint:
            raise BackendUnavailableError(
                f"LOCAL_HOST {server_name!r} has no endpoint",
            )

        url = _mcp_url(server.endpoint)
        try:
            response = await http.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "id": request.call_id or "1",
                    "method": "tools/call",
                    "params": {
                        "name": request.fingerprint.name,
                        "arguments": request.args,
                    },
                },
                headers={"Authorization": f"Bearer {token.serialized}"},
            )
        except httpx.HTTPError as exc:
            raise BackendUnavailableError(
                f"LOCAL_HOST {server_name!r}: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise BackendUnavailableError(
                f"LOCAL_HOST {server_name!r}: HTTP {response.status_code}",
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RemoteToolError(-32700, "malformed JSON-RPC response") from exc

        if "error" in body and body["error"] is not None:
            err = body["error"]
            raise RemoteToolError(
                code=int(err.get("code", -32000)),
                message=str(err.get("message", "")),
            )
        result = body.get("result") or {}
        if not isinstance(result, dict):
            return {"value": result}
        return result

    return invoke


def _mcp_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/mcp"):
        return base
    return f"{base}/mcp"
