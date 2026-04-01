"""Model comparison — run same prompt against multiple models."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient


@dataclass
class ModelResult:
    """Result from a single model invocation."""

    model: str
    content: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


@dataclass
class ComparisonResult:
    """Aggregated results from comparing multiple models."""

    models: list[str] = field(default_factory=list)
    results: list[ModelResult] = field(default_factory=list)
    task_type: str = ""


class ModelComparator:
    """Run the same prompt against multiple models in parallel."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def compare(
        self,
        messages: list[dict[str, Any]],
        models: list[str],
        *,
        task_type: str = "",
    ) -> ComparisonResult:
        """Run the same prompt against multiple models in parallel.

        Returns results for each model including content, latency, tokens.
        Models that error out are included with the error message.
        """
        tasks = [self._run_single(messages, model) for model in models]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return ComparisonResult(
            models=models,
            results=list(results),
            task_type=task_type,
        )

    async def _run_single(
        self,
        messages: list[dict[str, Any]],
        model: str,
    ) -> ModelResult:
        """Run a single model and capture result or error."""
        start = time.monotonic()
        try:
            response = await self._llm.complete(messages, model)
            elapsed = int((time.monotonic() - start) * 1000)
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = response.get("usage", {})
            return ModelResult(
                model=model,
                content=str(content),
                latency_ms=elapsed,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return ModelResult(model=model, error=str(exc), latency_ms=elapsed)
