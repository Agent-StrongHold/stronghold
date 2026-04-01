"""Plan-execute strategy: plan -> subtasks -> execute each -> review.

Three-phase reasoning:
1. Plan: LLM decomposes the request into numbered subtasks.
2. Execute: Each subtask is sent to the LLM (with optional tool dispatch).
3. Review: All results are sent for a final summary/review pass.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient

logger = logging.getLogger("stronghold.strategies.plan_execute")

# Matches lines like "1. Do something", "2) Do something", or "- Do something"
_SUBTASK_PATTERN = re.compile(r"^\s*(?:\d+[\.\)]\s+|- )\s*(.+)", re.MULTILINE)


def _parse_subtasks(plan_text: str) -> list[str]:
    """Extract subtask descriptions from a plan response.

    Recognises numbered lists (``1. ...``, ``2) ...``) and dash-prefixed
    lists (``- ...``).  Returns an empty list when the plan contains no
    recognisable structure so the caller can fall back.
    """
    matches = _SUBTASK_PATTERN.findall(plan_text)
    return [m.strip() for m in matches if m.strip()]


def _extract_content(response: dict[str, Any]) -> str:
    """Pull the assistant text out of an OpenAI-format response."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "") or ""


def _extract_usage(response: dict[str, Any]) -> tuple[int, int]:
    """Return (prompt_tokens, completion_tokens) from a response."""
    usage = response.get("usage", {})
    return usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


class PlanExecuteStrategy:
    """Plan then execute each subtask, then review.

    Works both with and without tools.  When ``tools`` and
    ``tool_executor`` are passed via *kwargs* the execute phase will
    honour tool calls from the LLM, dispatching them through the
    executor exactly as ReactStrategy does.
    """

    def __init__(self, max_subtasks: int = 10) -> None:
        self.max_subtasks = max_subtasks

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the full plan-execute-review pipeline."""
        total_input = 0
        total_output = 0
        tool_history: list[dict[str, Any]] = []

        # ── 1. Plan phase ────────────────────────────────────────────
        plan_prompt = (
            "You are a task planner. Decompose the user's request into "
            f"numbered subtasks (max {self.max_subtasks}). "
            "For each subtask, describe what to do and how to test it."
        )
        plan_messages: list[dict[str, Any]] = [
            {"role": "system", "content": plan_prompt},
            *messages,
        ]
        plan_response = await llm.complete(plan_messages, model)
        plan_text = _extract_content(plan_response)
        inp, out = _extract_usage(plan_response)
        total_input += inp
        total_output += out

        subtasks = _parse_subtasks(plan_text)

        # Fallback: if no subtasks parsed, return the plan text directly
        if not subtasks:
            return ReasoningResult(
                response=plan_text,
                done=True,
                input_tokens=total_input,
                output_tokens=total_output,
            )

        # Cap at max_subtasks
        subtasks = subtasks[: self.max_subtasks]

        # ── 2. Execute phase ─────────────────────────────────────────
        # Extract original system context (if any) for subtask messages
        system_context = ""
        for msg in messages:
            if msg.get("role") == "system":
                system_context = str(msg.get("content", ""))
                break

        # Extract original user request for context
        user_request = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_request = str(msg.get("content", ""))
                break

        subtask_results: list[str] = []
        tools: list[dict[str, Any]] | None = kwargs.get("tools")
        tool_executor: Any = kwargs.get("tool_executor")

        for i, subtask in enumerate(subtasks):
            logger.debug("Executing subtask %d/%d: %s", i + 1, len(subtasks), subtask[:80])

            exec_system = system_context or "You are a helpful assistant."
            exec_messages: list[dict[str, Any]] = [
                {"role": "system", "content": exec_system},
                {
                    "role": "user",
                    "content": (
                        f"Original request: {user_request}\n\n"
                        f"Subtask {i + 1}/{len(subtasks)}: {subtask}"
                    ),
                },
            ]

            result_text = await self._execute_subtask(
                exec_messages,
                model,
                llm,
                tools=tools,
                tool_executor=tool_executor,
                tool_history=tool_history,
                usage_accum=(total_input, total_output),
            )
            total_input, total_output = self._last_usage
            subtask_results.append(result_text)

        # ── 3. Review phase ──────────────────────────────────────────
        results_block = "\n\n".join(
            f"Subtask {i + 1} ({subtasks[i]}): {r}" for i, r in enumerate(subtask_results)
        )
        review_messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are reviewing the results of a multi-step plan. "
                    "Summarise the outcomes, note anything missed or needing "
                    "correction, and provide a final consolidated answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original request: {user_request}\n\n"
                    f"Subtask results:\n{results_block}\n\n"
                    "Please provide a final summary."
                ),
            },
        ]
        review_response = await llm.complete(review_messages, model)
        review_text = _extract_content(review_response)
        inp, out = _extract_usage(review_response)
        total_input += inp
        total_output += out

        return ReasoningResult(
            response=review_text,
            done=True,
            tool_history=tool_history,
            input_tokens=total_input,
            output_tokens=total_output,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    # Mutable accumulator written by _execute_subtask so the caller can
    # read updated totals without needing to return a tuple.
    _last_usage: tuple[int, int] = (0, 0)

    async def _execute_subtask(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None,
        tool_executor: Any,
        tool_history: list[dict[str, Any]],
        usage_accum: tuple[int, int],
    ) -> str:
        """Execute a single subtask, optionally dispatching tool calls.

        Returns the final assistant text for the subtask.
        """
        total_input, total_output = usage_accum
        current_messages = list(messages)
        max_tool_rounds = 3  # hard cap on tool-call rounds per subtask

        for round_num in range(max_tool_rounds + 1):
            response = await llm.complete(
                current_messages,
                model,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
            inp, out = _extract_usage(response)
            total_input += inp
            total_output += out

            choices = response.get("choices", [])
            message = choices[0] if choices else {}
            msg = message.get("message", {})
            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list):
                tool_calls = []

            # No tool calls or exhausted rounds -> return text
            if not tool_calls or round_num >= max_tool_rounds:
                self._last_usage = (total_input, total_output)
                return _extract_content(response)

            # Dispatch tool calls
            current_messages.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")

                try:
                    tool_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    tool_args = {}

                if tool_executor and callable(tool_executor):
                    tool_result = await tool_executor(tool_name, tool_args)
                else:
                    tool_result = f"Tool '{tool_name}' not available"

                tool_result_str = str(tool_result)

                tool_history.append(
                    {
                        "tool_name": tool_name,
                        "arguments": tool_args,
                        "result": tool_result_str,
                        "round": round_num,
                    }
                )

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": tool_result_str,
                    }
                )

        # Shouldn't be reached, but be safe
        self._last_usage = (total_input, total_output)
        return ""
