"""React strategy: LLM → tool calls → execute → feed back → repeat.

This is the core tool loop, ported from Conductor main.py:486-609.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.agents.messages import LLMResponse
from stronghold.agents.strategies.tool_loop import ToolLoop
from stronghold.tracing.pipeline import PipelineTrace
from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.strategies.react")


def _find_tool_schema(
    tools: list[dict[str, Any]] | None,
    tool_name: str,
) -> dict[str, Any]:
    """Find the parameter schema for a tool by name."""
    if not tools:
        return {}
    for tool in tools:
        fn = tool.get("function", {})
        if fn.get("name") == tool_name:
            params: dict[str, Any] = fn.get("parameters", {})
            return params
    return {}


class ReactStrategy:
    """ReAct loop: LLM call → tool dispatch → feed back → repeat."""

    def __init__(
        self,
        max_rounds: int = 3,
        force_tool_first: bool = False,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        trace: Trace | None = None,
        warden: Any = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the ReAct loop — fully traced if trace is provided."""
        pt = PipelineTrace(trace)
        loop = ToolLoop(
            tool_executor=tool_executor,
            trace=trace,
            tools=tools,
            sentinel=kwargs.get("sentinel"),
            warden=warden,
            auth=kwargs.get("auth"),
        )
        current_messages = list(messages)
        tool_history: list[dict[str, Any]] = []
        total_input_tokens = 0
        total_output_tokens = 0
        tool_choice = "required" if self.force_tool_first else "auto"

        for round_num in range(self.max_rounds + 1):
            if round_num > 0:
                tool_choice = "auto"

            with pt.span(f"llm_call_{round_num}") as ls:
                ls.set_input({"model": model, "message_count": len(current_messages)})
                resp = LLMResponse(
                    await llm.complete(
                        current_messages,
                        model,
                        tools=tools,
                        tool_choice=tool_choice if tools else None,
                    )
                )
                ls.set_usage(
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    model=model,
                )

            total_input_tokens += resp.input_tokens
            total_output_tokens += resp.output_tokens

            if not resp.tool_calls or round_num >= self.max_rounds:
                return ReasoningResult(
                    response=resp.content,
                    done=True,
                    tool_history=tool_history,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            current_messages.append(resp.message)
            await loop.run_calls(
                resp.tool_calls, current_messages, tool_history, round_num=round_num
            )

        return ReasoningResult(
            response="Max tool rounds reached",
            done=True,
            tool_history=tool_history,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
