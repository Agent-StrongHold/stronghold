"""Emissary HTTP binding — MCP-spec OAuth 2.1 + RFC 8707 + RFC 9728.

This module provides ``build_http_app`` which returns a Starlette ASGI app
wrapping an Emissary instance with the wire protocol expected by MCP
clients:

- ``GET /.well-known/oauth-protected-resource``      Protected Resource
   ``GET /.well-known/oauth-protected-resource/mcp``  Metadata (RFC 9728)
- ``POST /mcp``                                       JSON-RPC dispatch

Authorisation:

- Every request to ``/mcp`` requires a Bearer token.
- The token is validated by an injected ``TokenValidator`` against the
  resource's canonical URI (RFC 8707 audience binding).
- 401 responses include a ``WWW-Authenticate`` header pointing at the PRM
  document.
- 403 ``insufficient_scope`` responses carry the ``scope`` parameter
  listing the required scopes (per OAuth 2.1 §5.3).

The binding never holds master credentials — it consults Keyward inside
Emissary on every call_tool. Token-passthrough (forwarding the inbound
client token to a downstream) is explicitly prohibited by the MCP spec
and is not implemented.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from stronghold.mcp.emissary import (
    BackendUnavailableError,
    IdempotencyConflictError,
    MissingBackendError,
    SessionExpiredError,
    SessionOwnershipError,
    SessionUnknownError,
    UnauthorizedToolError,
)
from stronghold.types.security import (
    InsufficientScopeError,
    TokenAudienceMismatchError,
    TokenExpiredError,
    TokenValidationError,
    ToolCallRequest,
    ToolFingerprint,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from stronghold.protocols.security import MCPGateway, TokenValidator
    from stronghold.types.auth import AuthContext


def build_http_app(
    *,
    emissary: MCPGateway,
    token_validator: TokenValidator,
    canonical_uri: str,
    auth_servers: tuple[str, ...],
    scopes_supported: frozenset[str],
) -> Starlette:
    """Build the Starlette ASGI app for the Emissary HTTP binding."""

    metadata_url = f"{canonical_uri.rstrip('/')}/.well-known/oauth-protected-resource"

    async def prm(_request: Request) -> Response:
        return JSONResponse(
            {
                "resource": canonical_uri,
                "authorization_servers": list(auth_servers),
                "scopes_supported": sorted(scopes_supported),
                "bearer_methods_supported": ["header"],
            },
        )

    async def mcp_handler(request: Request) -> Response:
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return _unauthorized(metadata_url)

        raw = auth_header[len("Bearer ") :]
        try:
            auth = await token_validator.validate(raw, expected_audience=canonical_uri)
        except TokenAudienceMismatchError:
            return _unauthorized(metadata_url, error="invalid_token")
        except TokenExpiredError:
            return _unauthorized(metadata_url, error="invalid_token")
        except TokenValidationError:
            return _unauthorized(metadata_url, error="invalid_token")

        try:
            body = await request.json()
        except Exception:
            return _rpc_error(None, -32700, "Parse error")

        method = body.get("method")
        params = body.get("params") or {}
        rpc_id = body.get("id")

        try:
            if method == "tools/list":
                tools = await emissary.list_tools(auth=auth, session=None)
                return _ok(
                    rpc_id,
                    {
                        "tools": [
                            {
                                "name": tool.name,
                                "description": tool.description,
                                "inputSchema": tool.input_schema,
                            }
                            for tool in tools
                        ],
                    },
                )

            if method == "tools/call":
                tool_name = params.get("name")
                if not tool_name:
                    return _rpc_error(rpc_id, -32602, "missing tool name")
                fingerprint = await _resolve_fingerprint(emissary, tool_name, auth)
                if fingerprint is None:
                    return _rpc_error(rpc_id, -32602, f"unknown tool: {tool_name}")

                result = await emissary.call_tool(
                    ToolCallRequest(
                        fingerprint=fingerprint,
                        args=params.get("arguments") or {},
                        auth=auth,
                        call_id=str(rpc_id) if rpc_id is not None else "anonymous",
                    ),
                )
                return _ok(
                    rpc_id,
                    {"content": result.content, "isError": result.is_error},
                )

            return _rpc_error(rpc_id, -32601, f"method not found: {method}")

        except UnauthorizedToolError as exc:
            return _rpc_error(rpc_id, -32000, f"unauthorized: {exc}")
        except InsufficientScopeError as exc:
            return _forbidden_scope(metadata_url, exc.required)
        except IdempotencyConflictError:
            return _rpc_error(rpc_id, -32000, "idempotency conflict")
        except (SessionOwnershipError, SessionUnknownError, SessionExpiredError):
            return _rpc_error(rpc_id, -32000, "session invalid")
        except (BackendUnavailableError, MissingBackendError) as exc:
            return _rpc_error(rpc_id, -32000, f"backend unavailable: {exc}")

    return Starlette(
        routes=[
            Route("/.well-known/oauth-protected-resource", prm, methods=["GET"]),
            Route(
                "/.well-known/oauth-protected-resource/mcp",
                prm,
                methods=["GET"],
            ),
            Route("/mcp", mcp_handler, methods=["POST"]),
        ],
    )


# --- helpers ---------------------------------------------------------------


async def _resolve_fingerprint(
    emissary: MCPGateway,
    name: str,
    auth: AuthContext,
) -> ToolFingerprint | None:
    for descriptor in await emissary.list_tools(auth=auth, session=None):
        if descriptor.name == name:
            return descriptor.fingerprint
    return None


def _unauthorized(metadata_url: str, error: str | None = None) -> Response:
    parts = [f'Bearer resource_metadata="{metadata_url}"']
    if error:
        parts.append(f'error="{error}"')
    return Response(
        status_code=401,
        headers={"WWW-Authenticate": ", ".join(parts)},
    )


def _forbidden_scope(metadata_url: str, required: frozenset[str]) -> Response:
    return Response(
        status_code=403,
        headers={
            "WWW-Authenticate": (
                f'Bearer error="insufficient_scope", '
                f'scope="{" ".join(sorted(required))}", '
                f'resource_metadata="{metadata_url}"'
            ),
        },
    )


def _ok(rpc_id: Any, result: dict[str, Any]) -> Response:
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})


def _rpc_error(rpc_id: Any, code: int, message: str) -> Response:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}},
    )
