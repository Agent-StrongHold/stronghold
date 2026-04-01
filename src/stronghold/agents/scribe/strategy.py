"""Scribe agent: committee writing strategy.

Runs a configurable pipeline of stages (default: researcher, drafter,
critic, advocate, editor). Each stage makes one LLM call with a role-
specific system prompt plus the accumulated outputs from prior stages.
The final stage's output becomes the response.
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.types.agent import ReasoningResult

logger = logging.getLogger("stronghold.strategy.scribe")

DEFAULT_STAGES: tuple[str, ...] = (
    "researcher",
    "drafter",
    "critic",
    "advocate",
    "editor",
)

# Stage-specific system prompts. Each role gets instructions appropriate
# to its function in the writing committee.
_STAGE_PROMPTS: dict[str, str] = {
    "researcher": (
        "You are the Researcher on a writing committee. "
        "Gather facts, sources, and key points relevant to the user's request. "
        "Output structured research notes that a drafter can use."
    ),
    "drafter": (
        "You are the Drafter on a writing committee. "
        "Using the research provided, write a complete first draft that addresses "
        "the user's request. Focus on structure, flow, and completeness."
    ),
    "critic": (
        "You are the Critic on a writing committee. "
        "Review the draft and research. Identify weaknesses, logical gaps, "
        "unsupported claims, and areas that need improvement. Be specific and constructive."
    ),
    "advocate": (
        "You are the Advocate on a writing committee. "
        "Review the draft, research, and critique. Defend the strengths of the draft, "
        "highlight what works well, and suggest how to address the critique while "
        "preserving the piece's best qualities."
    ),
    "editor": (
        "You are the Editor on a writing committee. "
        "You have the final say. Synthesize the research, draft, critique, and advocacy "
        "into a polished final version. Fix issues raised by the critic while preserving "
        "strengths noted by the advocate. Output only the final text."
    ),
}


def _system_prompt_for(stage_name: str) -> str:
    """Return the system prompt for a stage, with a generic fallback."""
    if stage_name in _STAGE_PROMPTS:
        return _STAGE_PROMPTS[stage_name]
    return (
        f"You are the {stage_name} on a writing committee. "
        f"Fulfill your role as {stage_name} for the user's writing request. "
        "Build on the work of prior committee members."
    )


def _extract_content(response: dict[str, Any]) -> str:
    """Pull assistant content from an OpenAI-format response dict."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    return choices[0].get("message", {}).get("content", "") or ""


class ScribeStrategy:
    """Committee writing strategy: sequential LLM stages with accumulated context.

    Each stage receives a role-specific system prompt, the original user
    messages, and the outputs from all prior stages. The final stage's
    output is returned as the response.
    """

    def __init__(self, stages: tuple[str, ...] = DEFAULT_STAGES) -> None:
        if not stages:
            msg = "ScribeStrategy requires at least one stage"
            raise ValueError(msg)
        self.stages = stages

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the committee pipeline and return the final stage's output."""
        total_input = 0
        total_output = 0
        stage_outputs: list[tuple[str, str]] = []  # (stage_name, content)
        trace_parts: list[str] = []

        for stage_name in self.stages:
            stage_messages = self._build_stage_messages(
                stage_name,
                messages,
                stage_outputs,
            )

            response = await llm.complete(stage_messages, model)
            usage = response.get("usage", {})
            total_input += usage.get("prompt_tokens", 0)
            total_output += usage.get("completion_tokens", 0)

            content = _extract_content(response)
            stage_outputs.append((stage_name, content))
            trace_parts.append(f"{stage_name}: {len(content)} chars")

            logger.debug(
                "Scribe stage '%s' completed: %d chars",
                stage_name,
                len(content),
            )

        # Final output is the last stage's content
        final_content = stage_outputs[-1][1] if stage_outputs else ""
        reasoning_trace = "Scribe committee: " + " -> ".join(trace_parts)

        return ReasoningResult(
            response=final_content,
            done=True,
            input_tokens=total_input,
            output_tokens=total_output,
            reasoning_trace=reasoning_trace,
        )

    def _build_stage_messages(
        self,
        stage_name: str,
        user_messages: list[dict[str, Any]],
        prior_outputs: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        """Assemble messages for a single committee stage."""
        result: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt_for(stage_name)},
        ]

        # Include original user messages
        result.extend(user_messages)

        # Append prior stage outputs as context
        if prior_outputs:
            context_parts = [f"[{name}]\n{content}" for name, content in prior_outputs]
            result.append(
                {
                    "role": "user",
                    "content": (
                        "Previous committee members have produced the following:\n\n"
                        + "\n\n".join(context_parts)
                    ),
                }
            )

        return result
