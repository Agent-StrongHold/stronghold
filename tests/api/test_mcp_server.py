"""Tests for MCP server endpoint (ADR-K8S-020)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.mcp_server import router as mcp_router
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.types.tool import ToolDefinition
from tests.fakes import make_test_container

AUTH = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def mcp_app() -> FastAPI:
    app = FastAPI()
    app.include_router(mcp_router)

    # Build container with some tools registered
    tool_registry = InMemoryToolRegistry()
    tool_registry.register(
        ToolDefinition(
            name="web_search",
            description="Search the web",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        ),
        executor=lambda call, **kw: None,  # type: ignore[arg-type]
    )
    tool_registry.register(
        ToolDefinition(name="calculator", description="Do math"),
        executor=lambda call, **kw: None,  # type: ignore[arg-type]
    )

    container = make_test_container(tool_registry=tool_registry)
    app.state.container = container
    return app


@pytest.fixture
def client(mcp_app: FastAPI) -> TestClient:
    return TestClient(mcp_app)


def test_server_info(client: TestClient) -> None:
    resp = client.get("/mcp/", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "stronghold"
    assert "tools" in data["capabilities"]
    assert "prompts" in data["capabilities"]
    assert "resources" in data["capabilities"]


def test_tools_list(client: TestClient) -> None:
    resp = client.get("/mcp/tools/list", headers=AUTH)
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    names = {t["name"] for t in tools}
    assert "web_search" in names
    assert "calculator" in names
    # MCP format: inputSchema not parameters
    ws = next(t for t in tools if t["name"] == "web_search")
    assert "inputSchema" in ws
    assert ws["inputSchema"]["properties"]["query"]["type"] == "string"


def test_tools_list_requires_auth(client: TestClient) -> None:
    resp = client.get("/mcp/tools/list")
    assert resp.status_code == 401


def test_tools_call_missing_name(client: TestClient) -> None:
    resp = client.post("/mcp/tools/call", json={}, headers=AUTH)
    assert resp.status_code == 400


def test_prompts_list(client: TestClient) -> None:
    resp = client.get("/mcp/prompts/list", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "prompts" in data


def test_prompts_get_not_found(client: TestClient) -> None:
    resp = client.get("/mcp/prompts/get?name=nonexistent", headers=AUTH)
    assert resp.status_code == 404


def test_prompts_get_missing_param(client: TestClient) -> None:
    resp = client.get("/mcp/prompts/get", headers=AUTH)
    assert resp.status_code == 400


def test_resources_list(client: TestClient) -> None:
    resp = client.get("/mcp/resources/list", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "resources" in data


def test_resources_read_missing_uri(client: TestClient) -> None:
    resp = client.post("/mcp/resources/read", json={}, headers=AUTH)
    assert resp.status_code == 400


def test_resources_read_not_found(client: TestClient) -> None:
    resp = client.post("/mcp/resources/read", json={"uri": "stronghold://global/nothing"}, headers=AUTH)
    # Either 404 (catalog exists, resource not found) or 404 (no catalog)
    assert resp.status_code == 404
