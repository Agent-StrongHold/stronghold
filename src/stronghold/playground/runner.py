"""Prompt playground — test prompt changes before promoting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.prompts import PromptManager


@dataclass
class PlaygroundResult:
    """Result from a single playground run."""

    content: str = ""
    model: str = ""
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""


@dataclass
class ComparisonRun:
    """Result from comparing test vs production prompts."""

    test_result: PlaygroundResult = field(default_factory=PlaygroundResult)
    production_result: PlaygroundResult | None = None


@dataclass
class CaseResult:
    """Result from a single test case in a suite run."""

    input_text: str = ""
    expected_contains: list[str] = field(default_factory=list)
    actual_content: str = ""
    passed: bool = False


class PlaygroundRunner:
    """Runs prompt tests against an LLM backend.

    Supports single runs, side-by-side comparison, and batch test suites.
    """

    def __init__(
        self,
        llm: LLMClient,
        prompt_manager: PromptManager | None = None,
    ) -> None:
        self._llm = llm
        self._prompts = prompt_manager

    async def run(
        self,
        *,
        system_prompt: str,
        test_messages: list[dict[str, Any]],
        model: str = "auto",
    ) -> PlaygroundResult:
        """Run a single prompt test."""
        start = time.monotonic()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *test_messages,
        ]
        try:
            resp = await self._llm.complete(messages, model)
            elapsed = int((time.monotonic() - start) * 1000)
            choices = resp.get("choices", [{}])
            content = str(choices[0].get("message", {}).get("content", "")) if choices else ""
            usage = resp.get("usage", {})
            return PlaygroundResult(
                content=content,
                model=model,
                latency_ms=elapsed,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.monotonic() - start) * 1000)
            return PlaygroundResult(
                model=model,
                error=str(exc),
                latency_ms=elapsed,
            )

    async def compare(
        self,
        *,
        test_prompt: str,
        production_prompt: str,
        test_messages: list[dict[str, Any]],
        model: str = "auto",
    ) -> ComparisonRun:
        """Run test prompt vs production prompt side-by-side."""
        import asyncio  # noqa: PLC0415

        test_task = self.run(
            system_prompt=test_prompt,
            test_messages=test_messages,
            model=model,
        )
        prod_task = self.run(
            system_prompt=production_prompt,
            test_messages=test_messages,
            model=model,
        )
        test_result, prod_result = await asyncio.gather(test_task, prod_task)
        return ComparisonRun(test_result=test_result, production_result=prod_result)

    async def run_suite(
        self,
        *,
        system_prompt: str,
        test_cases: list[dict[str, Any]],
        model: str = "auto",
    ) -> list[CaseResult]:
        """Run a batch of test cases.

        Each test case has 'input' and optional 'expected_contains'.
        """
        results: list[CaseResult] = []
        for tc in test_cases:
            msgs: list[dict[str, Any]] = [
                {"role": "user", "content": tc.get("input", "")},
            ]
            pr = await self.run(
                system_prompt=system_prompt,
                test_messages=msgs,
                model=model,
            )
            expected: list[str] = tc.get("expected_contains", [])
            passed = (
                all(exp.lower() in pr.content.lower() for exp in expected) if expected else True
            )
            results.append(
                CaseResult(
                    input_text=tc.get("input", ""),
                    expected_contains=expected,
                    actual_content=pr.content,
                    passed=passed,
                )
            )
        return results
