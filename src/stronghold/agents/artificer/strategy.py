"""Artificer strategy: plan → architect → phase loop (code → check → fix → commit).

This is the real engineering workflow, not a single-shot LLM call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from stronghold.agents.messages import LLMResponse
from stronghold.agents.strategies.tool_loop import ToolLoop
from stronghold.tracing.pipeline import PipelineTrace
from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.artificer")

# Type for async status callback
StatusCallback = Callable[[str], Coroutine[Any, Any, None]]


async def _noop_status(msg: str) -> None:
    pass


class ArtificerStrategy:
    """Multi-phase engineering workflow.

    1. Plan: decompose into phases
    2. For each phase:
       a. Write code (via write_file tool)
       b. Run quality checks (pytest, ruff, mypy, bandit)
       c. If fail: fix and recheck (max 2 retries)
       d. Commit when green
    3. Return summary of all phases
    """

    def __init__(
        self,
        max_phases: int = 5,
        max_retries_per_phase: int = 2,
    ) -> None:
        self.max_phases = max_phases
        self.max_retries = max_retries_per_phase

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        status_callback: StatusCallback | None = None,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the full plan-execute workflow — fully traced."""
        pt = PipelineTrace(trace)
        status = status_callback or _noop_status
        tool_history: list[dict[str, Any]] = []

        loop = ToolLoop(
            tool_executor=tool_executor,
            trace=trace,
            tools=tools,
            sentinel=kwargs.get("sentinel"),
            auth=kwargs.get("auth"),
            pii_filter=False,
            status_callback=status,
            on_tool_result=self._make_result_logger(status),
        )

        # Phase 1: Plan — traced
        await status("Planning...")
        with pt.span("artificer.plan") as ps:
            ps.set_input({"model": model, "message_count": len(messages)})
            plan = await self._plan(messages, model, llm)
            ps.set_output({"plan_length": len(plan), "plan_lines": plan.count("\n")})

        await status(f"Plan complete ({plan.count(chr(10))} lines)")
        logger.info("Artificer plan generated: %d chars", len(plan))

        await asyncio.sleep(2)

        # Phase 2: Execute each step with tool calls
        results: list[str] = [f"## Plan\n{plan}"]
        current_messages = list(messages)
        current_messages.append({"role": "assistant", "content": plan})
        current_messages.append(
            {
                "role": "user",
                "content": (
                    "Now execute the plan above. For each step:\n"
                    "1. Use write_file to create/modify files\n"
                    "2. Use run_pytest to verify tests pass\n"
                    "3. Use run_ruff_check and run_mypy to verify code quality\n"
                    "4. Use git_commit when a step is complete\n\n"
                    "Execute step by step. Start with step 1."
                ),
            }
        )

        await status("Executing plan...")

        for round_num in range(self.max_phases * 3):
            with pt.span(f"llm_call_{round_num}") as ls:
                ls.set_input({"model": model, "message_count": len(current_messages)})
                resp = LLMResponse(
                    await llm.complete(current_messages, model, tools=tools, tool_choice="auto")
                )
                ls.set_usage(
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    model=model,
                )

            if not resp.tool_calls:
                results.append(f"\n## Result\n{resp.content}")
                await status("Complete")
                return ReasoningResult(
                    response="\n\n".join(results),
                    done=True,
                    tool_history=tool_history,
                )

            current_messages.append(resp.message)
            await loop.run_calls(
                resp.tool_calls, current_messages, tool_history, round_num=round_num
            )
            await asyncio.sleep(1)

        await status("Max rounds reached")
        return ReasoningResult(
            response="\n\n".join(results) + "\n\nMax rounds reached.",
            done=True,
            tool_history=tool_history,
        )

    @staticmethod
    def _make_result_logger(status: StatusCallback) -> Any:
        """Return an on_tool_result callback that logs pytest/ruff/mypy outcomes."""

        async def _log(tool_name: str, result_str: str) -> None:
            preview = result_str[:200]
            if '"passed": true' in preview or '"status": "ok"' in preview:
                await status(f"{tool_name}: OK")
            elif '"passed": false' in preview:
                await status(f"{tool_name}: FAILED — fixing...")
            elif '"error":' in preview and '"status": "failed"' in preview:
                await status(f"{tool_name}: error — retrying...")

        return _log

    async def _plan(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
    ) -> str:
        """Generate a plan by asking the LLM to decompose the task."""
        plan_messages = list(messages)
        plan_messages.append(
            {
                "role": "user",
                "content": (
                    "Before writing any code, create a detailed plan. "
                    "Break the task into numbered phases. For each phase:\n"
                    "- What files to create/modify\n"
                    "- What tests to write\n"
                    "- What the acceptance criteria are\n\n"
                    "Output ONLY the plan, no code yet."
                ),
            }
        )
        return LLMResponse(await llm.complete(plan_messages, model)).content or "No plan generated"
