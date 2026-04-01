"""Forge agent: iterative tool/agent creation with validation loop.

The Forge creates SKILL.md files via an LLM, then validates them
before accepting.  If validation fails the errors are fed back to the
LLM for another attempt, up to ``max_iterations`` rounds.

Dangerous patterns (exec, eval, subprocess, etc.) are rejected
deterministically — the LLM never gets to bypass the safety check.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.agents.forge.strategy")

DANGEROUS_PATTERNS: list[str] = [
    "exec(",
    "eval(",
    "import os",
    "subprocess",
    "__import__",
]

_REQUIRED_FRONTMATTER_FIELDS: list[str] = [
    "name",
    "description",
    "version",
    "trust_tier",
]


class ValidationError(Exception):
    """Raised when a SKILL.md fails validation."""

    def __init__(self, message: str, *, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors: list[str] = errors or []


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Extract YAML frontmatter from ``---`` fences.

    Returns the key-value pairs as a dict, or ``None`` if no valid
    frontmatter block is found.
    """
    stripped = text.strip()
    if not stripped.startswith("---"):
        return None

    # Find closing ---
    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return None

    frontmatter_block = stripped[3:end_idx].strip()
    if not frontmatter_block:
        return None

    result: dict[str, str] = {}
    for line in frontmatter_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip().strip('"').strip("'")

    return result


def validate_skill_md(content: str) -> list[str]:
    """Validate a SKILL.md string.  Returns a list of error strings (empty = valid).

    Checks:
    1. Valid YAML frontmatter with ``---`` fences.
    2. Required fields: name, description, version, trust_tier.
    3. No dangerous code patterns anywhere in the content.
    """
    errors: list[str] = []

    if not content or not content.strip():
        errors.append("Empty SKILL.md content")
        return errors

    # 1. Frontmatter presence
    frontmatter = _parse_frontmatter(content)
    if frontmatter is None:
        errors.append("Missing or invalid YAML frontmatter (must be enclosed in --- fences)")
        # Still check for dangerous patterns even without frontmatter
    else:
        # 2. Required fields
        for field in _REQUIRED_FRONTMATTER_FIELDS:
            if field not in frontmatter or not frontmatter[field]:
                errors.append(f"Missing required frontmatter field: {field}")

    # 3. Dangerous patterns
    for pattern in DANGEROUS_PATTERNS:
        if pattern in content:
            errors.append(f"Dangerous pattern detected: {pattern}")

    return errors


class ForgeStrategy:
    """Iterative SKILL.md creation: LLM generates -> validate -> retry on failure.

    The loop runs up to ``max_iterations`` times.  Each failed attempt
    feeds the validation errors back to the LLM so it can self-correct.
    """

    def __init__(self, max_iterations: int = 10) -> None:
        self.max_iterations = max_iterations

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run the iterative generation loop."""
        current_messages = list(messages)
        total_input_tokens = 0
        total_output_tokens = 0
        last_errors: list[str] = []

        for iteration in range(1, self.max_iterations + 1):
            # ── LLM call ──────────────────────────────────────────
            if trace:
                with trace.span(f"forge_iteration_{iteration}") as span:
                    span.set_input({"model": model, "iteration": iteration})
                    response = await llm.complete(current_messages, model)
                    usage = response.get("usage", {})
                    span.set_usage(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        model=model,
                    )
            else:
                response = await llm.complete(current_messages, model)
                usage = response.get("usage", {})

            total_input_tokens += usage.get("prompt_tokens", 0)
            total_output_tokens += usage.get("completion_tokens", 0)

            # Extract content
            choices = response.get("choices", [])
            choice = choices[0] if choices else {}
            content: str = choice.get("message", {}).get("content", "")

            # ── Validate ──────────────────────────────────────────
            last_errors = validate_skill_md(content)

            if not last_errors:
                # Valid SKILL.md produced
                logger.info(
                    "Forge produced valid SKILL.md on iteration %d/%d",
                    iteration,
                    self.max_iterations,
                )
                return ReasoningResult(
                    response=content,
                    done=True,
                    reasoning_trace=(
                        f"Forge: valid SKILL.md produced on iteration {iteration}"
                        f"/{self.max_iterations}"
                    ),
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                )

            # ── Feed errors back ──────────────────────────────────
            logger.info(
                "Forge iteration %d/%d failed validation: %s",
                iteration,
                self.max_iterations,
                "; ".join(last_errors),
            )

            error_feedback = (
                "The SKILL.md you generated has validation errors. "
                "Please fix the following issues and regenerate:\n\n"
                + "\n".join(f"- {e}" for e in last_errors)
            )
            # Append the LLM's attempt + our feedback so it can self-correct
            current_messages.append({"role": "assistant", "content": content})
            current_messages.append({"role": "user", "content": error_feedback})

        # ── Exhausted all iterations ──────────────────────────────
        error_summary = "; ".join(last_errors)
        logger.warning(
            "Forge exhausted %d iterations. Last errors: %s",
            self.max_iterations,
            error_summary,
        )
        return ReasoningResult(
            response=(
                f"Failed to generate a valid SKILL.md after {self.max_iterations} "
                f"iterations. Last validation errors: {error_summary}"
            ),
            done=True,
            reasoning_trace=(
                f"Forge: failed after {self.max_iterations} iterations. "
                f"Last errors: {error_summary}"
            ),
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
        )
