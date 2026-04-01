"""Tests for Scribe committee writing strategy.

ScribeStrategy runs a configurable pipeline of committee stages
(default: researcher, drafter, critic, advocate, editor), each making
one LLM call with its own system prompt plus the accumulated outputs
from prior stages.
"""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.scribe.strategy import ScribeStrategy
from tests.fakes import FakeLLMClient

# ── Helpers ─────────────────────────────────────────────────────────────


def _make_response(content: str, input_tok: int = 10, output_tok: int = 20) -> dict[str, Any]:
    """Build an OpenAI-format response dict."""
    return {
        "id": "chatcmpl-scribe-test",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tok,
            "completion_tokens": output_tok,
            "total_tokens": input_tok + output_tok,
        },
    }


# ── Default pipeline (5 stages) ────────────────────────────────────────


class TestScribeDefaultPipeline:
    """ScribeStrategy with the default 5-stage committee."""

    async def test_returns_editor_output(self) -> None:
        """Final result is the editor (last stage) output."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("Research notes on topic X."),
            _make_response("First draft of the article."),
            _make_response("Critique: needs stronger opening."),
            _make_response("Advocacy: the thesis is compelling."),
            _make_response("Final polished article."),
        )
        strategy = ScribeStrategy()
        result = await strategy.reason(
            [{"role": "user", "content": "Write an article about AI safety"}],
            "test-model",
            llm,
        )
        assert result.response == "Final polished article."
        assert result.done is True

    async def test_makes_five_llm_calls(self) -> None:
        """Default pipeline has 5 stages, so 5 LLM calls."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("research"),
            _make_response("draft"),
            _make_response("critique"),
            _make_response("advocacy"),
            _make_response("edited"),
        )
        strategy = ScribeStrategy()
        await strategy.reason(
            [{"role": "user", "content": "Write something"}],
            "test-model",
            llm,
        )
        assert len(llm.calls) == 5

    async def test_each_stage_receives_prior_outputs(self) -> None:
        """Each stage after the first gets accumulated output from prior stages."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("RESEARCH_OUTPUT"),
            _make_response("DRAFT_OUTPUT"),
            _make_response("CRITIQUE_OUTPUT"),
            _make_response("ADVOCACY_OUTPUT"),
            _make_response("EDITOR_OUTPUT"),
        )
        strategy = ScribeStrategy()
        await strategy.reason(
            [{"role": "user", "content": "Write something"}],
            "test-model",
            llm,
        )
        # Stage 2 (drafter) should see research output
        drafter_messages = llm.calls[1]["messages"]
        drafter_text = " ".join(m.get("content", "") for m in drafter_messages)
        assert "RESEARCH_OUTPUT" in drafter_text

        # Stage 5 (editor) should see all prior outputs
        editor_messages = llm.calls[4]["messages"]
        editor_text = " ".join(m.get("content", "") for m in editor_messages)
        assert "RESEARCH_OUTPUT" in editor_text
        assert "DRAFT_OUTPUT" in editor_text
        assert "CRITIQUE_OUTPUT" in editor_text
        assert "ADVOCACY_OUTPUT" in editor_text

    async def test_each_stage_has_system_prompt(self) -> None:
        """Each stage gets a system prompt identifying its role."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("r"),
            _make_response("d"),
            _make_response("c"),
            _make_response("a"),
            _make_response("e"),
        )
        strategy = ScribeStrategy()
        await strategy.reason(
            [{"role": "user", "content": "Write something"}],
            "test-model",
            llm,
        )
        # Each call should have a system message as the first message
        for i, call in enumerate(llm.calls):
            msgs = call["messages"]
            system_msgs = [m for m in msgs if m.get("role") == "system"]
            assert len(system_msgs) >= 1, f"Stage {i} missing system prompt"

    async def test_user_message_forwarded_to_all_stages(self) -> None:
        """The original user request appears in every stage's messages."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("r"),
            _make_response("d"),
            _make_response("c"),
            _make_response("a"),
            _make_response("e"),
        )
        strategy = ScribeStrategy()
        await strategy.reason(
            [{"role": "user", "content": "Write about penguins"}],
            "test-model",
            llm,
        )
        for i, call in enumerate(llm.calls):
            msgs = call["messages"]
            user_texts = [m.get("content", "") for m in msgs if m.get("role") == "user"]
            assert any("Write about penguins" in t for t in user_texts), (
                f"Stage {i} missing user message"
            )

    async def test_model_passed_to_all_stages(self) -> None:
        """The specified model is used for every LLM call."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("r"),
            _make_response("d"),
            _make_response("c"),
            _make_response("a"),
            _make_response("e"),
        )
        strategy = ScribeStrategy()
        await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "scribe-model-7b",
            llm,
        )
        for call in llm.calls:
            assert call["model"] == "scribe-model-7b"


# ── Custom stages ───────────────────────────────────────────────────────


class TestScribeCustomStages:
    """ScribeStrategy with user-configured stage lists."""

    async def test_two_stage_pipeline(self) -> None:
        """Minimal pipeline: drafter + editor."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("Raw draft text."),
            _make_response("Polished final text."),
        )
        strategy = ScribeStrategy(stages=("drafter", "editor"))
        result = await strategy.reason(
            [{"role": "user", "content": "Write a poem"}],
            "test-model",
            llm,
        )
        assert result.response == "Polished final text."
        assert result.done is True
        assert len(llm.calls) == 2

    async def test_single_stage_pipeline(self) -> None:
        """Degenerate case: single stage still works."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response("One-shot output."))
        strategy = ScribeStrategy(stages=("drafter",))
        result = await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        assert result.response == "One-shot output."
        assert result.done is True
        assert len(llm.calls) == 1

    async def test_custom_stage_names_in_prompts(self) -> None:
        """Custom stage names appear in the system prompts."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("outline"),
            _make_response("final"),
        )
        strategy = ScribeStrategy(stages=("outliner", "finalizer"))
        await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        # First call system prompt should mention "outliner"
        first_system = llm.calls[0]["messages"][0]["content"]
        assert "outliner" in first_system.lower()
        # Second call system prompt should mention "finalizer"
        second_system = llm.calls[1]["messages"][0]["content"]
        assert "finalizer" in second_system.lower()


# ── Token tracking ──────────────────────────────────────────────────────


class TestScribeTokenTracking:
    """ScribeStrategy must accumulate tokens across all stages."""

    async def test_tokens_accumulated_across_stages(self) -> None:
        """Token counts sum across all committee stages."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("r", input_tok=10, output_tok=20),
            _make_response("d", input_tok=15, output_tok=25),
            _make_response("c", input_tok=20, output_tok=30),
            _make_response("a", input_tok=25, output_tok=35),
            _make_response("e", input_tok=30, output_tok=40),
        )
        strategy = ScribeStrategy()
        result = await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        assert result.input_tokens == 10 + 15 + 20 + 25 + 30
        assert result.output_tokens == 20 + 25 + 30 + 35 + 40

    async def test_tokens_single_stage(self) -> None:
        """Single stage reports its own token counts."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response("out", input_tok=42, output_tok=99))
        strategy = ScribeStrategy(stages=("writer",))
        result = await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        assert result.input_tokens == 42
        assert result.output_tokens == 99


# ── Edge cases ──────────────────────────────────────────────────────────


class TestScribeEdgeCases:
    """Edge cases and robustness tests."""

    async def test_empty_llm_response_propagates(self) -> None:
        """An empty response from a stage is passed along without crashing."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response(""),  # empty research
            _make_response("Draft based on empty research."),
        )
        strategy = ScribeStrategy(stages=("researcher", "drafter"))
        result = await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        assert result.response == "Draft based on empty research."
        assert result.done is True

    async def test_no_choices_in_response(self) -> None:
        """Handles malformed LLM response with no choices."""
        llm = FakeLLMClient()
        llm.set_responses(
            {"id": "fake", "choices": [], "usage": {}},
        )
        strategy = ScribeStrategy(stages=("writer",))
        result = await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        assert result.response == ""
        assert result.done is True

    async def test_multi_message_conversation_forwarded(self) -> None:
        """A multi-turn conversation is forwarded to each stage."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("research"),
            _make_response("draft"),
        )
        msgs = [
            {"role": "user", "content": "Write about dogs"},
            {"role": "assistant", "content": "Sure, what angle?"},
            {"role": "user", "content": "Adoption rates"},
        ]
        strategy = ScribeStrategy(stages=("researcher", "drafter"))
        await strategy.reason(msgs, "test-model", llm)

        # Both calls should include the full conversation
        for call in llm.calls:
            user_msgs = [m for m in call["messages"] if m.get("role") == "user"]
            user_text = " ".join(m.get("content", "") for m in user_msgs)
            assert "dogs" in user_text or "Adoption" in user_text

    async def test_reasoning_trace_populated(self) -> None:
        """The reasoning_trace field captures stage progression."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("r"),
            _make_response("d"),
        )
        strategy = ScribeStrategy(stages=("researcher", "drafter"))
        result = await strategy.reason(
            [{"role": "user", "content": "Write"}],
            "test-model",
            llm,
        )
        assert "researcher" in result.reasoning_trace.lower()
        assert "drafter" in result.reasoning_trace.lower()


# ── Default stages constant ────────────────────────────────────────────


class TestScribeDefaults:
    """Test default configuration values."""

    def test_default_stages(self) -> None:
        strategy = ScribeStrategy()
        assert strategy.stages == ("researcher", "drafter", "critic", "advocate", "editor")

    def test_custom_stages_stored(self) -> None:
        strategy = ScribeStrategy(stages=("a", "b", "c"))
        assert strategy.stages == ("a", "b", "c")

    def test_empty_stages_raises(self) -> None:
        with pytest.raises(ValueError, match="[Ss]tage"):
            ScribeStrategy(stages=())
