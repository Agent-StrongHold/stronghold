"""Legacy tool wrapper for Conductor migration.

Adapts Conductor's HTTP-based tool interface to Stronghold's ToolExecutor protocol.
Each legacy tool is an HTTP endpoint that accepts JSON and returns JSON.
This is a migration bridge — tools should eventually get proper MCP servers.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from stronghold.types.tool import ToolDefinition

logger = logging.getLogger("stronghold.tools.legacy")


@dataclass
class LegacyToolConfig:
    """Configuration for a legacy Conductor tool."""

    name: str
    endpoint: str  # HTTP URL
    method: str = "POST"
    timeout: float = 15.0
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)  # JSON Schema


@dataclass
class LegacyToolStats:
    """Track usage of legacy tools for migration prioritization."""

    name: str
    call_count: int = 0
    last_called: float = 0.0
    error_count: int = 0


class LegacyToolWrapper:
    """Wraps legacy Conductor HTTP tools as Stronghold ToolExecutors."""

    def __init__(self, tools: list[LegacyToolConfig] | None = None) -> None:
        self._tools: dict[str, LegacyToolConfig] = {}
        self._stats: dict[str, LegacyToolStats] = {}
        if tools:
            for t in tools:
                self.register(t)

    def register(self, config: LegacyToolConfig) -> None:
        """Register a legacy tool."""
        self._tools[config.name] = config
        self._stats[config.name] = LegacyToolStats(name=config.name)

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered legacy tools as MCP-compatible definitions."""
        result: list[dict[str, Any]] = []
        for cfg in self._tools.values():
            params = cfg.parameters if cfg.parameters else {"type": "object", "properties": {}}
            result.append(
                {
                    "name": cfg.name,
                    "description": cfg.description,
                    "parameters": params,
                }
            )
        return result

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a legacy tool by proxying to its HTTP endpoint.

        Logs deprecation warning on every call.
        Returns MCP-compatible tool result.
        """
        cfg = self._tools.get(name)
        if cfg is None:
            return {"success": False, "content": "", "error": f"Unknown tool: {name} not found"}

        # Track stats
        stats = self._stats[name]
        stats.call_count += 1
        stats.last_called = time.time()

        logger.warning(
            "Legacy tool '%s' called — this is a deprecated Conductor bridge. "
            "Migrate to an MCP server.",
            name,
        )

        try:
            async with httpx.AsyncClient(timeout=cfg.timeout) as client:
                if cfg.method.upper() == "GET":
                    resp = await client.get(cfg.endpoint, params=arguments)
                else:
                    resp = await client.post(cfg.endpoint, json=arguments)

                if resp.status_code == 200:  # noqa: PLR2004
                    data = resp.json()
                    content = str(data.get("result", data.get("content", str(data))))
                    return {"success": True, "content": content}

                stats.error_count += 1
                return {
                    "success": False,
                    "content": "",
                    "error": f"HTTP {resp.status_code} from legacy tool '{name}'",
                }
        except (httpx.TimeoutException, httpx.ReadTimeout) as exc:
            stats.error_count += 1
            return {
                "success": False,
                "content": "",
                "error": f"Timeout calling legacy tool '{name}': {exc}",
            }
        except Exception as exc:
            stats.error_count += 1
            return {
                "success": False,
                "content": "",
                "error": f"Error calling legacy tool '{name}': {exc}",
            }

    def get_stats(self) -> list[LegacyToolStats]:
        """Get usage stats for all legacy tools (for migration prioritization)."""
        return list(self._stats.values())

    def to_tool_definitions(self) -> list[ToolDefinition]:
        """Convert to Stronghold ToolDefinition format."""
        defs: list[ToolDefinition] = []
        for cfg in self._tools.values():
            params = cfg.parameters if cfg.parameters else {"type": "object", "properties": {}}
            defs.append(
                ToolDefinition(
                    name=cfg.name,
                    description=cfg.description,
                    parameters=params,
                    endpoint=cfg.endpoint,
                )
            )
        return defs
