"""Tests for legacy tool wrapper: Conductor HTTP tool migration bridge."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
import pytest
import respx

from stronghold.tools.legacy import LegacyToolConfig, LegacyToolStats, LegacyToolWrapper
from stronghold.types.tool import ToolDefinition


class TestRegister:
    def test_register_adds_tool(self) -> None:
        wrapper = LegacyToolWrapper()
        cfg = LegacyToolConfig(name="weather", endpoint="https://api.example.com/weather")
        wrapper.register(cfg)
        tools = wrapper.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "weather"

    def test_register_via_constructor(self) -> None:
        configs = [
            LegacyToolConfig(name="a", endpoint="https://api.example.com/a"),
            LegacyToolConfig(name="b", endpoint="https://api.example.com/b"),
        ]
        wrapper = LegacyToolWrapper(tools=configs)
        assert len(wrapper.list_tools()) == 2

    def test_register_overwrites_existing(self) -> None:
        wrapper = LegacyToolWrapper()
        cfg1 = LegacyToolConfig(
            name="tool", endpoint="https://api.example.com/v1", description="v1"
        )
        cfg2 = LegacyToolConfig(
            name="tool", endpoint="https://api.example.com/v2", description="v2"
        )
        wrapper.register(cfg1)
        wrapper.register(cfg2)
        tools = wrapper.list_tools()
        assert len(tools) == 1
        assert tools[0]["description"] == "v2"


class TestListTools:
    def test_list_tools_returns_mcp_compatible(self) -> None:
        wrapper = LegacyToolWrapper()
        cfg = LegacyToolConfig(
            name="search",
            endpoint="https://api.example.com/search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        )
        wrapper.register(cfg)
        tools = wrapper.list_tools()
        assert len(tools) == 1
        tool = tools[0]
        assert tool["name"] == "search"
        assert tool["description"] == "Search the web"
        assert "properties" in tool["parameters"]
        assert "query" in tool["parameters"]["properties"]

    def test_list_tools_empty(self) -> None:
        wrapper = LegacyToolWrapper()
        assert wrapper.list_tools() == []


class TestExecute:
    @respx.mock
    async def test_execute_proxies_to_http_endpoint(self) -> None:
        endpoint = "https://api.example.com/weather"
        respx.post(endpoint).mock(
            return_value=httpx.Response(200, json={"result": "sunny"})
        )
        cfg = LegacyToolConfig(name="weather", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        result = await wrapper.execute("weather", {"city": "NYC"})
        assert result["success"] is True
        assert result["content"] == "sunny"

    @respx.mock
    async def test_execute_logs_deprecation_warning(self, caplog: Any) -> None:
        endpoint = "https://api.example.com/old_tool"
        respx.post(endpoint).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        cfg = LegacyToolConfig(name="old_tool", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.legacy"):
            await wrapper.execute("old_tool", {})
        assert any("deprecated" in r.message.lower() or "legacy" in r.message.lower()
                    for r in caplog.records)

    @respx.mock
    async def test_execute_handles_http_error(self) -> None:
        endpoint = "https://api.example.com/failing"
        respx.post(endpoint).mock(
            return_value=httpx.Response(500, json={"error": "internal"})
        )
        cfg = LegacyToolConfig(name="failing", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        result = await wrapper.execute("failing", {})
        assert result["success"] is False
        assert "500" in result.get("error", "")

    @respx.mock
    async def test_execute_handles_timeout(self) -> None:
        endpoint = "https://api.example.com/slow"
        respx.post(endpoint).mock(side_effect=httpx.ReadTimeout("timed out"))
        cfg = LegacyToolConfig(name="slow", endpoint=endpoint, timeout=0.1)
        wrapper = LegacyToolWrapper(tools=[cfg])
        result = await wrapper.execute("slow", {})
        assert result["success"] is False
        assert "timeout" in result.get("error", "").lower() or "timed out" in result.get("error", "").lower()

    async def test_execute_unknown_tool(self) -> None:
        wrapper = LegacyToolWrapper()
        result = await wrapper.execute("nonexistent", {})
        assert result["success"] is False
        assert "not found" in result.get("error", "").lower() or "unknown" in result.get("error", "").lower()

    @respx.mock
    async def test_execute_with_get_method(self) -> None:
        endpoint = "https://api.example.com/status"
        respx.get(endpoint).mock(
            return_value=httpx.Response(200, json={"result": "healthy"})
        )
        cfg = LegacyToolConfig(name="status", endpoint=endpoint, method="GET")
        wrapper = LegacyToolWrapper(tools=[cfg])
        result = await wrapper.execute("status", {"check": "all"})
        assert result["success"] is True
        assert result["content"] == "healthy"

    @respx.mock
    async def test_execute_handles_connection_error(self) -> None:
        endpoint = "https://api.example.com/unreachable"
        respx.post(endpoint).mock(side_effect=httpx.ConnectError("connection refused"))
        cfg = LegacyToolConfig(name="unreachable", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        result = await wrapper.execute("unreachable", {})
        assert result["success"] is False
        assert result.get("error")


class TestStats:
    @respx.mock
    async def test_stats_call_count_increments(self) -> None:
        endpoint = "https://api.example.com/tool"
        respx.post(endpoint).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        cfg = LegacyToolConfig(name="tool", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        await wrapper.execute("tool", {})
        await wrapper.execute("tool", {})
        stats = wrapper.get_stats()
        assert len(stats) == 1
        assert stats[0].call_count == 2

    @respx.mock
    async def test_stats_last_called_updates(self) -> None:
        endpoint = "https://api.example.com/tool"
        respx.post(endpoint).mock(
            return_value=httpx.Response(200, json={"result": "ok"})
        )
        cfg = LegacyToolConfig(name="tool", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        before = time.time()
        await wrapper.execute("tool", {})
        stats = wrapper.get_stats()
        assert stats[0].last_called >= before

    @respx.mock
    async def test_stats_error_count_increments(self) -> None:
        endpoint = "https://api.example.com/flaky"
        respx.post(endpoint).mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )
        cfg = LegacyToolConfig(name="flaky", endpoint=endpoint)
        wrapper = LegacyToolWrapper(tools=[cfg])
        await wrapper.execute("flaky", {})
        await wrapper.execute("flaky", {})
        stats = wrapper.get_stats()
        assert stats[0].error_count == 2
        assert stats[0].call_count == 2

    def test_get_stats_empty(self) -> None:
        wrapper = LegacyToolWrapper()
        assert wrapper.get_stats() == []


class TestToToolDefinitions:
    def test_to_tool_definitions_format(self) -> None:
        cfg = LegacyToolConfig(
            name="legacy_search",
            endpoint="https://api.example.com/search",
            description="Legacy search tool",
            parameters={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        )
        wrapper = LegacyToolWrapper(tools=[cfg])
        defs = wrapper.to_tool_definitions()
        assert len(defs) == 1
        d = defs[0]
        assert isinstance(d, ToolDefinition)
        assert d.name == "legacy_search"
        assert d.description == "Legacy search tool"
        assert d.parameters["properties"]["q"]["type"] == "string"
        assert d.endpoint == "https://api.example.com/search"

    def test_to_tool_definitions_empty(self) -> None:
        wrapper = LegacyToolWrapper()
        assert wrapper.to_tool_definitions() == []

    def test_to_tool_definitions_default_parameters(self) -> None:
        cfg = LegacyToolConfig(name="simple", endpoint="https://api.example.com/simple")
        wrapper = LegacyToolWrapper(tools=[cfg])
        defs = wrapper.to_tool_definitions()
        assert defs[0].parameters == {"type": "object", "properties": {}}
