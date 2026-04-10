"""Unit tests for RuntimePipeline LLM helpers and auditor verdict parsing.

Uses FakeLLMClient to script responses and verify retry/extraction behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from stronghold.builders.extractors import ExtractionError, extract_python_code
from stronghold.builders.pipeline import RuntimePipeline

if TYPE_CHECKING:
    pass

from tests.fakes import FakeLLMClient, FakePromptManager


def _make_response(content: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def _pipeline(fake_llm: FakeLLMClient) -> RuntimePipeline:
    fake_td = AsyncMock()
    return RuntimePipeline(
        llm=fake_llm,
        tool_dispatcher=fake_td,
        prompt_manager=FakePromptManager(),
    )


# ── _llm_call ────────────────────────────────────────────────────────


class TestLlmCall:
    async def test_returns_content_string(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("hello world"))
        p = _pipeline(llm)
        result = await p._llm_call("prompt", "model-a")
        assert result == "hello world"

    async def test_empty_content_returns_empty_string(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response(""))
        p = _pipeline(llm)
        result = await p._llm_call("prompt", "model-a")
        assert result == ""

    async def test_missing_choices_returns_empty_string(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses({"choices": [], "usage": {}})
        p = _pipeline(llm)
        result = await p._llm_call("prompt", "model-a")
        assert result == ""

    async def test_records_call_on_fake(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("ok"))
        p = _pipeline(llm)
        await p._llm_call("my prompt", "model-x")
        assert len(llm.calls) == 1
        assert llm.calls[0]["model"] == "model-x"
        assert llm.calls[0]["messages"][0]["content"] == "my prompt"


# ── _llm_extract ─────────────────────────────────────────────────────


class TestLlmExtract:
    async def test_succeeds_on_first_try(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("```python\ndef foo(): pass\n```"))
        p = _pipeline(llm)
        result = await p._llm_extract("prompt", "model", extract_python_code, "test code")
        assert "def foo" in result

    async def test_retries_on_extraction_error(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("not python code"),        # attempt 1: junk
            _make_response("still not python code"),  # attempt 2: junk
            _make_response("```python\ndef bar(): return 1\n```"),  # attempt 3: valid
        )
        p = _pipeline(llm)
        result = await p._llm_extract("prompt", "model", extract_python_code, "test code")
        assert "def bar" in result
        assert len(llm.calls) == 3

    async def test_raises_after_max_retries(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("junk 1"),
            _make_response("junk 2"),
            _make_response("junk 3"),
        )
        p = _pipeline(llm)
        with pytest.raises(ExtractionError):
            await p._llm_extract("prompt", "model", extract_python_code, "test code")

    async def test_retry_prompt_includes_error(self) -> None:
        """Second call's prompt should mention the parse failure."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("not code"),
            _make_response("```python\ndef ok(): pass\n```"),
        )
        p = _pipeline(llm)
        await p._llm_extract("original prompt", "model", extract_python_code, "test")
        assert len(llm.calls) == 2
        retry_prompt = llm.calls[1]["messages"][0]["content"]
        assert "could not be parsed" in retry_prompt


# ── auditor_review ───────────────────────────────────────────────────


class TestAuditorReview:
    async def test_approved_uppercase(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("APPROVED\nLooks good"))
        p = _pipeline(llm)
        approved, text = await p.auditor_review("test_stage", {"key": "value"})
        assert approved is True
        assert "APPROVED" in text

    async def test_verdict_approved_with_colon(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("VERDICT: APPROVED\nAll checks pass"))
        p = _pipeline(llm)
        approved, _ = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is True

    async def test_verdict_approved_no_space(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("VERDICT:APPROVED"))
        p = _pipeline(llm)
        approved, _ = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is True

    async def test_changes_requested(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("CHANGES_REQUESTED\nFix the thing"))
        p = _pipeline(llm)
        approved, text = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is False
        assert "Fix the thing" in text

    async def test_verdict_changes_with_colon(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response("VERDICT: CHANGES_REQUESTED\nNope"))
        p = _pipeline(llm)
        approved, _ = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is False

    async def test_no_verdict_defaults_to_approved(self) -> None:
        """When LLM response has no verdict keyword, default is approved."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response("Everything looks fine to me, no issues found."))
        p = _pipeline(llm)
        approved, _ = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is True

    async def test_empty_response_defaults_to_approved(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(_make_response(""))
        p = _pipeline(llm)
        approved, text = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is True
        assert text == ""

    async def test_markdown_header_approved(self) -> None:
        """# APPROVED should parse — lstrip('#') in pipeline.py:2889."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response("# APPROVED\n\nAll good"))
        p = _pipeline(llm)
        approved, _ = await p.auditor_review("test_stage", {"k": "v"})
        assert approved is True
