"""Outbound MCP client.

Drives Emissary's ``REMOTE_PROXY`` backend. Spec-compliant per the Model
Context Protocol authorization spec:

- Discovery via RFC 9728 Protected Resource Metadata at
  ``{server_url}/.well-known/oauth-protected-resource``.
- Per-call audience binding: the bearer token's ``aud`` must equal the
  target server's canonical URI before any network call. Forwarding a
  token whose ``aud`` doesn't match is forbidden by the MCP spec
  (§"Access Token Privilege Restriction") and raises
  ``TokenAudiencePassthroughError``.
- 401 with ``WWW-Authenticate: Bearer resource_metadata="…"`` invalidates
  the PRM cache and surfaces ``RemoteUnauthorizedError``.
- 403 ``insufficient_scope`` parses the required scopes and surfaces
  ``RemoteScopeChallengeError``.
- HTTPS-only by default; ``dev_mode`` accepts ``localhost`` only.

Master credentials never live here — Keyward holds them and mints the
audience-bound bearer token the client receives.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx

from stronghold.types.security import (
    RemoteScopeChallengeError,
    RemoteToolError,
    RemoteUnauthorizedError,
    ServerMetadata,
    TokenAudiencePassthroughError,
    ToolDescriptor,
)

if TYPE_CHECKING:
    from stronghold.types.security import IssuedToken


_DEFAULT_PRM_TTL = timedelta(minutes=5)
_WWW_AUTHENTICATE_RESOURCE_METADATA = re.compile(
    r'resource_metadata="([^"]+)"',
    re.IGNORECASE,
)
_WWW_AUTHENTICATE_SCOPE = re.compile(r'scope="([^"]+)"', re.IGNORECASE)


class MCPClient:
    """Outbound MCP client for the Emissary REMOTE_PROXY backend."""

    def __init__(
        self,
        *,
        http: httpx.AsyncClient | None = None,
        dev_mode: bool = False,
        prm_ttl: timedelta = _DEFAULT_PRM_TTL,
    ) -> None:
        # One pooled AsyncClient per MCPClient instance; callers may override
        # for tests (httpx.MockTransport) or for connection-pool tuning.
        self._http = http if http is not None else httpx.AsyncClient(timeout=30)
        self._owns_http = http is None
        self._dev_mode = dev_mode
        self._prm_ttl = prm_ttl
        self._prm_cache: dict[str, tuple[ServerMetadata, datetime]] = {}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # --- discovery -------------------------------------------------------

    async def discover(self, server_url: str) -> ServerMetadata:
        self._enforce_https(server_url)

        cached = self._prm_cache.get(server_url)
        if cached is not None and cached[1] > _now():
            return cached[0]

        prm_url = self._prm_url_for(server_url)
        response = await self._http.get(prm_url)
        if response.status_code != 200:
            raise RemoteUnauthorizedError(
                f"PRM unavailable at {prm_url} ({response.status_code})",
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise RemoteUnauthorizedError(f"malformed PRM at {prm_url}") from exc

        canonical_uri = data.get("resource") or server_url
        auth_servers = tuple(data.get("authorization_servers") or ())
        scopes_supported = frozenset(data.get("scopes_supported") or ())
        metadata = ServerMetadata(
            canonical_uri=str(canonical_uri),
            auth_servers=tuple(str(s) for s in auth_servers),
            scopes_supported=scopes_supported,
        )
        self._prm_cache[server_url] = (metadata, _now() + self._prm_ttl)
        return metadata

    def invalidate_prm(self, server_url: str) -> None:
        self._prm_cache.pop(server_url, None)

    # --- data plane ------------------------------------------------------

    async def list_tools(
        self,
        server: ServerMetadata,
        token: IssuedToken,
    ) -> list[ToolDescriptor]:
        body = await self._json_rpc(server, token, "tools/list", {})
        # MCP spec: result.tools is a list of {name, description, inputSchema}.
        # We surface them as ToolDescriptor with no fingerprint (the catalog
        # owns fingerprints; this is just a directory).
        from stronghold.security import tool_fingerprint as fp
        from stronghold.types.security import Scope, TargetKind, TrustTier

        out: list[ToolDescriptor] = []
        for declaration in body.get("tools") or []:
            descriptor = ToolDescriptor(
                fingerprint=fp.compute(declaration),
                name=str(declaration.get("name", "")),
                description=str(declaration.get("description", "")),
                input_schema=dict(declaration.get("inputSchema") or {}),
                target_kind=TargetKind.REMOTE_PROXY,
                trust_tier=TrustTier.T3,
                scope=Scope.PLATFORM,
            )
            out.append(descriptor)
        return out

    async def call_tool(
        self,
        server: ServerMetadata,
        tool_name: str,
        args: dict[str, Any],
        token: IssuedToken,
    ) -> dict[str, Any]:
        return await self._json_rpc(
            server,
            token,
            "tools/call",
            {"name": tool_name, "arguments": args},
        )

    # --- internals -------------------------------------------------------

    async def _json_rpc(
        self,
        server: ServerMetadata,
        token: IssuedToken,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        # Token-passthrough check: refuse before any network call.
        if token.audience != server.canonical_uri:
            raise TokenAudiencePassthroughError(
                f"token aud={token.audience!r} != server={server.canonical_uri!r}",
            )

        url = self._mcp_url_for(server.canonical_uri)
        self._enforce_https(url)

        payload = {
            "jsonrpc": "2.0",
            "id": _next_rpc_id(),
            "method": method,
            "params": params,
        }
        response = await self._http.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token.serialized}"},
        )

        if response.status_code == 401:
            self.invalidate_prm(server.canonical_uri)
            header = response.headers.get("WWW-Authenticate", "")
            match = _WWW_AUTHENTICATE_RESOURCE_METADATA.search(header)
            raise RemoteUnauthorizedError(
                "401 from remote MCP server",
                resource_metadata=match.group(1) if match else None,
            )
        if response.status_code == 403:
            header = response.headers.get("WWW-Authenticate", "")
            match = _WWW_AUTHENTICATE_SCOPE.search(header)
            required = frozenset(match.group(1).split()) if match else frozenset()
            raise RemoteScopeChallengeError(required, message=header)
        if response.status_code >= 400:
            raise RemoteToolError(
                code=response.status_code,
                message=f"HTTP {response.status_code}: {response.text[:200]}",
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

    def _enforce_https(self, url: str) -> None:
        if url.startswith("https://"):
            return
        if self._dev_mode and (
            url.startswith("http://localhost") or url.startswith("http://127.0.0.1")
        ):
            return
        raise RemoteToolError(
            code=-32000,
            message=f"refusing non-HTTPS URL {url!r}; set dev_mode=True for localhost",
        )

    def _prm_url_for(self, server_url: str) -> str:
        # Per RFC 9728 §3.1: PRM is served at the well-known URI under the
        # resource's authority. We accept both the bare authority form and
        # the path-rooted form (sub-path PRM).
        base = server_url.rstrip("/")
        if base.endswith("/mcp"):
            authority = base[: -len("/mcp")]
            return f"{authority}/.well-known/oauth-protected-resource/mcp"
        return f"{base}/.well-known/oauth-protected-resource"

    def _mcp_url_for(self, canonical_uri: str) -> str:
        base = canonical_uri.rstrip("/")
        if base.endswith("/mcp"):
            return base
        return f"{base}/mcp"


# --- helpers ---------------------------------------------------------------


_RPC_COUNTER = 0


def _next_rpc_id() -> int:
    global _RPC_COUNTER
    _RPC_COUNTER += 1
    return _RPC_COUNTER


def _now() -> datetime:
    return datetime.now(UTC)
