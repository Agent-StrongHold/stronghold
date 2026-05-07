"""ToolLoop — shared one-round tool-call processor for multi-step strategies.

All strategies that run tool loops (React, Artificer, and any future multi-step
strategy) instantiate this class once per reason() call and delegate every
tool-call round to run_calls(). This eliminates the duplicated parse → validate
→ execute → scan → record cycle.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast

from stronghold.agents.messages import _MAX_TOOL_RESULT_BYTES, ToolResult
from stronghold.tracing.pipeline import PipelineTrace

if TYPE_CHECKING:
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.strategies.tool_loop")

_MAX_ARG_BYTES = 32_768


def _find_tool_schema(
    tools: list[dict[str, Any]] | None,
    tool_name: str,
) -> dict[str, Any]:
    """Return the parameter schema for a named tool, or {} if not found."""
    if not tools:
        return {}
    for tool in tools:
        fn = tool.get("function", {})
        if fn.get("name") == tool_name:
            params: dict[str, Any] = fn.get("parameters", {})
            return params
    return {}


class ToolLoop:
    """Processes one round of tool calls: parse → validate → execute → scan → record.

    Instantiate once per strategy.reason() call with the session's dependencies.
    Call run_calls() for each LLM response that contains tool_calls.
    """

    def __init__(
        self,
        *,
        tool_executor: Any,
        trace: Trace | None,
        tools: list[dict[str, Any]] | None = None,
        sentinel: Any = None,
        warden: Any = None,
        auth: Any = None,
        pii_filter: bool = True,
        status_callback: Any = None,
        on_tool_result: Any = None,
        max_arg_bytes: int = _MAX_ARG_BYTES,
        max_result_bytes: int = _MAX_TOOL_RESULT_BYTES,
    ) -> None:
        self._executor = tool_executor
        self._trace = PipelineTrace(trace)
        self._tools = tools
        self._sentinel = sentinel
        self._warden = warden
        self._auth = auth
        self._pii_filter = pii_filter
        self._status = status_callback
        self._on_result = on_tool_result
        self._max_arg_bytes = max_arg_bytes
        self._max_result_bytes = max_result_bytes

    async def run_calls(
        self,
        tool_calls: list[dict[str, Any]],
        current_messages: list[dict[str, Any]],
        tool_history: list[dict[str, Any]],
        *,
        round_num: int = 0,
    ) -> None:
        """Process all tool calls in one round, mutating messages and history in place."""
        for tc in tool_calls:
            await self._run_one(tc, current_messages, tool_history, round_num)

    async def _run_one(
        self,
        tc: dict[str, Any],
        current_messages: list[dict[str, Any]],
        tool_history: list[dict[str, Any]],
        round_num: int,
    ) -> None:
        fn = tc.get("function", {})
        tool_name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")

        tool_args, blocked_result = self._parse_args(tool_name, raw_args)

        if blocked_result is None:
            tool_args, blocked_result = await self._sentinel_pre(tool_name, tool_args)

        if blocked_result is not None:
            result_str = blocked_result
        else:
            raw_result = await self._execute(tool_name, tool_args)
            result_str = ToolResult(raw_result, self._max_result_bytes).content
            result_str = await self._post_scan(tool_name, result_str)

        if self._on_result is not None:
            await self._on_result(tool_name, result_str)

        tool_history.append(
            {
                "tool_name": tool_name,
                "arguments": tool_args,
                "result": result_str,
                "round": round_num,
            }
        )
        current_messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result_str,
            }
        )

    def _parse_args(self, tool_name: str, raw_args: str) -> tuple[dict[str, Any], str | None]:
        """Parse JSON args. Returns (args, error_str) — error_str non-None means blocked."""
        if len(raw_args.encode()) > self._max_arg_bytes:
            logger.warning("Tool %s arg size exceeds %d byte limit", tool_name, self._max_arg_bytes)
            return {}, f"Error: tool arguments exceed {self._max_arg_bytes} byte limit"
        try:
            return json.loads(raw_args), None
        except json.JSONDecodeError:
            logger.warning("Malformed tool arguments for %s: %s", tool_name, raw_args[:200])
            return {}, None

    async def _sentinel_pre(
        self, tool_name: str, tool_args: dict[str, Any]
    ) -> tuple[dict[str, Any], str | None]:
        """Sentinel pre-call check. Returns (possibly-repaired args, error or None)."""
        if self._sentinel is None or self._auth is None:
            return tool_args, None
        schema = _find_tool_schema(self._tools, tool_name)
        verdict = await self._sentinel.pre_call(tool_name, tool_args, self._auth, schema)
        if not verdict.allowed:
            return tool_args, f"Error: Permission denied for tool '{tool_name}'"
        if verdict.repaired_data:
            return verdict.repaired_data, None
        return tool_args, None

    async def _execute(self, tool_name: str, tool_args: dict[str, Any]) -> Any:
        """Execute tool via executor, wrapped in a trace span."""
        if self._status is not None:
            await self._status(f"Running {tool_name}...")
        if not self._executor or not callable(self._executor):
            return f"Tool '{tool_name}' not available"
        with self._trace.span(f"tool.{tool_name}") as ts:
            ts.set_input(tool_args)
            result = await self._executor(tool_name, tool_args)
            preview = str(result)[:300]
            ts.set_output(
                {
                    "success": (
                        not preview.startswith("Error") and "error" not in preview[:50].lower()
                    ),
                    "result_preview": preview,
                }
            )
        return result

    async def _post_scan(self, tool_name: str, result_str: str) -> str:
        """Sentinel post-call scan, or warden + optional PII filter fallback."""
        if self._sentinel is not None and self._auth is not None:
            return cast("str", await self._sentinel.post_call(tool_name, result_str, self._auth))
        if self._warden is not None:
            verdict = await self._warden.scan(result_str, "tool_result")
            if not verdict.clean:
                return (
                    f"[BLOCKED: tool result contained suspicious content: "
                    f"{', '.join(verdict.flags)}]"
                )
        if self._pii_filter:
            from stronghold.security.sentinel.pii_filter import scan_and_redact  # noqa: PLC0415

            result_str, _ = scan_and_redact(result_str)
        return result_str
