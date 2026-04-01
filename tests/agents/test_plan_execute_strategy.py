"""Tests for PlanExecuteStrategy: plan -> execute subtasks -> review -> combine."""

import json

import pytest

from stronghold.agents.strategies.plan_execute import PlanExecuteStrategy
from tests.fakes import FakeLLMClient


def _make_response(content: str) -> dict:
    """Build a minimal OpenAI-format chat completion response."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _make_tool_call_response(tool_name: str, arguments: dict) -> dict:
    """Build a response with a tool call."""
    return {
        "id": "chatcmpl-fake",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "tc_1",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


class TestPlanPhase:
    """Plan phase: LLM decomposes request into numbered subtasks."""

    async def test_plan_produces_subtasks_from_numbered_list(self) -> None:
        """LLM returns a numbered list; strategy parses into subtasks."""
        llm = FakeLLMClient()
        plan_text = "1. Read the input file\n2. Parse the CSV data\n3. Generate the report"
        # Plan response, then 3 execute responses, then review response
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Read file done"),
            _make_response("Parsed CSV done"),
            _make_response("Report generated"),
            _make_response("All tasks completed successfully."),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "process the CSV and generate a report"}],
            "test-model",
            llm,
        )
        assert result.done is True
        # Strategy should have made 5 LLM calls: plan + 3 execute + review
        assert len(llm.calls) == 5

    async def test_plan_parses_dash_prefixed_subtasks(self) -> None:
        """LLM returns dash-prefixed list items; strategy parses them."""
        llm = FakeLLMClient()
        plan_text = "- First thing\n- Second thing"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("First done"),
            _make_response("Second done"),
            _make_response("Review: all good"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "do two things"}],
            "test-model",
            llm,
        )
        assert result.done is True
        # plan + 2 execute + review = 4
        assert len(llm.calls) == 4

    async def test_plan_prompt_includes_max_subtasks(self) -> None:
        """The planning system prompt should reference the max_subtasks limit."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("1. Only one step"),
            _make_response("Step done"),
            _make_response("Review complete"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=7)
        await strategy.reason(
            [{"role": "user", "content": "plan something"}],
            "test-model",
            llm,
        )
        # The first call is the plan call; check system prompt
        plan_call_msgs = llm.calls[0]["messages"]
        system_msg = next(m for m in plan_call_msgs if m["role"] == "system")
        assert "7" in system_msg["content"]


class TestMaxSubtasks:
    """max_subtasks should cap the number of subtasks executed."""

    async def test_caps_at_max_subtasks(self) -> None:
        """If LLM returns more subtasks than max, only max are executed."""
        llm = FakeLLMClient()
        # Plan with 5 steps, but max_subtasks=3
        plan_text = (
            "1. Step one\n2. Step two\n3. Step three\n4. Step four\n5. Step five"
        )
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Done 1"),
            _make_response("Done 2"),
            _make_response("Done 3"),
            _make_response("Review: completed first 3"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=3)
        result = await strategy.reason(
            [{"role": "user", "content": "do five things"}],
            "test-model",
            llm,
        )
        assert result.done is True
        # plan + 3 execute (capped) + review = 5
        assert len(llm.calls) == 5


class TestExecutePhase:
    """Execute phase: each subtask is sent to LLM individually."""

    async def test_subtask_messages_include_original_context(self) -> None:
        """Each subtask execution should include original system context."""
        llm = FakeLLMClient()
        plan_text = "1. Do the thing"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Thing done"),
            _make_response("Review ok"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        original_msgs = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "do the thing"},
        ]
        await strategy.reason(original_msgs, "test-model", llm)

        # The execute call (index 1) should contain system context + subtask
        execute_msgs = llm.calls[1]["messages"]
        # Should have a system message with original context
        system_msgs = [m for m in execute_msgs if m["role"] == "system"]
        assert len(system_msgs) >= 1
        # Should reference the subtask
        user_msgs = [m for m in execute_msgs if m["role"] == "user"]
        assert any("Do the thing" in m["content"] for m in user_msgs)


class TestReviewPhase:
    """Review phase: all subtask results sent to LLM for final review."""

    async def test_review_includes_all_subtask_results(self) -> None:
        """Review call should include original request and all subtask results."""
        llm = FakeLLMClient()
        plan_text = "1. Alpha\n2. Beta"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Alpha result"),
            _make_response("Beta result"),
            _make_response("Final review: everything looks good"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "do alpha and beta"}],
            "test-model",
            llm,
        )
        # The review call is the last one (index 3)
        review_msgs = llm.calls[3]["messages"]
        # Review messages should mention subtask results
        review_text = " ".join(m.get("content", "") for m in review_msgs)
        assert "Alpha result" in review_text
        assert "Beta result" in review_text

    async def test_final_response_is_review_output(self) -> None:
        """The strategy result should be the review phase output."""
        llm = FakeLLMClient()
        plan_text = "1. Step one"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Step one done"),
            _make_response("Final summary: all completed."),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "do it"}],
            "test-model",
            llm,
        )
        assert result.response == "Final summary: all completed."


class TestFallbackBehavior:
    """When plan has no parseable subtasks, return plan text directly."""

    async def test_no_parseable_subtasks_returns_plan_directly(self) -> None:
        """If the plan response has no numbered/dashed items, return it as-is."""
        llm = FakeLLMClient()
        # A plan response with no numbered or dashed items
        plan_text = "I can help you with that directly. The answer is 42."
        llm.set_responses(_make_response(plan_text))
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "what is the meaning of life?"}],
            "test-model",
            llm,
        )
        assert result.response == plan_text
        assert result.done is True
        # Only the plan call was made, no execute or review
        assert len(llm.calls) == 1


class TestToolCallsInExecute:
    """Execute phase should handle tool calls when tools are provided."""

    async def test_tool_calls_executed_during_subtask(self) -> None:
        """When a subtask triggers a tool call, it should be executed."""
        llm = FakeLLMClient()
        plan_text = "1. Read the file"
        tool_call_resp = _make_tool_call_response("read_file", {"path": "data.csv"})
        llm.set_responses(
            _make_response(plan_text),
            # Execute subtask 1: LLM requests tool call, then gets result, then responds
            tool_call_resp,
            _make_response("File contents processed"),
            # Review
            _make_response("Review: file was read successfully"),
        )

        tool_calls_made: list[tuple[str, dict]] = []

        async def tool_executor(name: str, args: dict) -> str:
            tool_calls_made.append((name, args))
            return "col1,col2\n1,2\n3,4"

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ]

        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "read and process data.csv"}],
            "test-model",
            llm,
            tools=tools,
            tool_executor=tool_executor,
        )
        assert result.done is True
        assert len(tool_calls_made) == 1
        assert tool_calls_made[0][0] == "read_file"
        assert tool_calls_made[0][1] == {"path": "data.csv"}


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    async def test_empty_messages_returns_empty_result(self) -> None:
        """Empty message list should produce an empty-ish result."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response(""))
        strategy = PlanExecuteStrategy()
        result = await strategy.reason([], "test-model", llm)
        assert result.done is True

    async def test_reasoning_result_done_is_true_on_completion(self) -> None:
        """ReasoningResult.done should be True when strategy completes."""
        llm = FakeLLMClient()
        plan_text = "1. One step"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Step done"),
            _make_response("Review done"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "simple task"}],
            "test-model",
            llm,
        )
        assert result.done is True

    async def test_token_tracking(self) -> None:
        """Input/output tokens should be accumulated across all phases."""
        llm = FakeLLMClient()
        plan_text = "1. Step A"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("A done"),
            _make_response("Review done"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        result = await strategy.reason(
            [{"role": "user", "content": "count tokens"}],
            "test-model",
            llm,
        )
        # 3 calls x 10 prompt_tokens = 30, 3 calls x 20 completion_tokens = 60
        assert result.input_tokens == 30
        assert result.output_tokens == 60

    async def test_default_max_subtasks_is_10(self) -> None:
        """Default max_subtasks should be 10."""
        strategy = PlanExecuteStrategy()
        assert strategy.max_subtasks == 10

    async def test_model_forwarded_to_all_llm_calls(self) -> None:
        """The model parameter should be passed to every LLM call."""
        llm = FakeLLMClient()
        plan_text = "1. Single step"
        llm.set_responses(
            _make_response(plan_text),
            _make_response("Done"),
            _make_response("Review"),
        )
        strategy = PlanExecuteStrategy(max_subtasks=10)
        await strategy.reason(
            [{"role": "user", "content": "task"}],
            "my-special-model",
            llm,
        )
        for call in llm.calls:
            assert call["model"] == "my-special-model"
