"""MCP server endpoint — Stronghold exposes its catalogs via MCP protocol.

ADR-K8S-020: Stronghold acts as an MCP server, exposing three affordances:
  - tools/list + tools/call (from Tool Catalog)
  - prompts/list + prompts/get (from Skill Catalog)
  - resources/list + resources/read (from Resource Catalog)

This implements the JSON-RPC layer per the MCP specification.
HTTP+SSE transport is handled by the FastAPI route structure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.mcp_server")

router = APIRouter(prefix="/mcp")

# MCP protocol version
MCP_VERSION = "2024-11-05"


async def _get_auth(request: Request) -> Any:
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers),
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


# ── Server Info ──────────────────────────────────────────────────────


@router.get("/")
async def server_info(request: Request) -> JSONResponse:
    """MCP server capability advertisement."""
    return JSONResponse(content={
        "name": "stronghold",
        "version": "0.1.0",
        "protocolVersion": MCP_VERSION,
        "capabilities": {
            "tools": {"listChanged": False},
            "prompts": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
        },
    })


# ── Tools (from Tool Catalog) ───────────────────────────────────────


@router.get("/tools/list")
async def tools_list(request: Request) -> JSONResponse:
    """MCP tools/list — return all tools visible to the caller."""
    auth = await _get_auth(request)
    container = request.app.state.container

    tool_registry = container.tool_registry
    tools_raw = tool_registry.list_all()

    tools = [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.parameters,
        }
        for t in tools_raw
    ]
    return JSONResponse(content={"tools": tools})


@router.post("/tools/call")
async def tools_call(request: Request) -> JSONResponse:
    """MCP tools/call — execute a tool by name."""
    auth = await _get_auth(request)
    container = request.app.state.container
    body = await request.json()

    tool_name = body.get("name")
    arguments = body.get("arguments", {})

    if not tool_name:
        raise HTTPException(status_code=400, detail="Missing 'name' field")

    dispatcher = container.tool_dispatcher
    from stronghold.types.tool import ToolCall

    tool_call = ToolCall(id="mcp-call", name=tool_name, arguments=arguments)
    result = await dispatcher.dispatch(tool_call, auth_context=auth)

    return JSONResponse(content={
        "content": [{"type": "text", "text": result.content}],
        "isError": not result.success,
    })


# ── Prompts / Skills (from Skill Catalog) ────────────────────────────


@router.get("/prompts/list")
async def prompts_list(request: Request) -> JSONResponse:
    """MCP prompts/list — return all skills visible to the caller."""
    auth = await _get_auth(request)
    container = request.app.state.container

    org_id = auth.org_id if hasattr(auth, "org_id") else ""
    skills = container.skill_registry.list_all(org_id=org_id) if hasattr(container, "skill_registry") else []

    prompts = [
        {
            "name": s.name,
            "description": s.description,
            "arguments": [
                {"name": k, "description": "", "required": k in s.parameters.get("required", [])}
                for k in s.parameters.get("properties", {})
            ],
        }
        for s in skills
    ]
    return JSONResponse(content={"prompts": prompts})


@router.get("/prompts/get")
async def prompts_get(request: Request) -> JSONResponse:
    """MCP prompts/get — return a skill's system prompt by name."""
    auth = await _get_auth(request)
    container = request.app.state.container
    name = request.query_params.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name' query param")

    org_id = auth.org_id if hasattr(auth, "org_id") else ""
    skill = container.skill_registry.get(name, org_id=org_id) if hasattr(container, "skill_registry") else None

    if not skill:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    return JSONResponse(content={
        "description": skill.description,
        "messages": [
            {"role": "user", "content": {"type": "text", "text": skill.system_prompt}},
        ],
    })


# ── Resources (from Resource Catalog) ────────────────────────────────


@router.get("/resources/list")
async def resources_list(request: Request) -> JSONResponse:
    """MCP resources/list — return all resources visible to the caller."""
    auth = await _get_auth(request)

    # Resource catalog is optional — may not be wired yet
    container = request.app.state.container
    if not hasattr(container, "resource_catalog"):
        return JSONResponse(content={"resources": []})

    tenant_id = auth.org_id if hasattr(auth, "org_id") else ""
    user_id = auth.user_id if hasattr(auth, "user_id") else ""
    entries = container.resource_catalog.list_resources(
        tenant_id=tenant_id, user_id=user_id,
    )

    resources = [
        {
            "uri": e.uri_template,
            "name": e.uri_template.split("/")[-1],
            "description": e.description,
            "mimeType": e.mime_type,
        }
        for e in entries
    ]
    return JSONResponse(content={"resources": resources})


@router.post("/resources/read")
async def resources_read(request: Request) -> JSONResponse:
    """MCP resources/read — resolve a resource URI."""
    auth = await _get_auth(request)
    body = await request.json()
    uri = body.get("uri")
    if not uri:
        raise HTTPException(status_code=400, detail="Missing 'uri' field")

    container = request.app.state.container
    if not hasattr(container, "resource_catalog"):
        raise HTTPException(status_code=404, detail="Resource catalog not available")

    tenant_id = auth.org_id if hasattr(auth, "org_id") else ""
    user_id = auth.user_id if hasattr(auth, "user_id") else ""

    result = await container.resource_catalog.resolve(
        uri, tenant_id=tenant_id, user_id=user_id,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"Resource '{uri}' not found or access denied")

    return JSONResponse(content={
        "contents": [
            {
                "uri": result.uri,
                "mimeType": result.mime_type,
                "text": result.content,
            },
        ],
    })
