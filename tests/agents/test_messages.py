"""Tests for agents/messages.py: extract_user_text, LLMResponse, ToolResult."""

from stronghold.agents.messages import LLMResponse, ToolResult, extract_user_text


class TestNoUserMessage:
    def test_empty_messages(self) -> None:
        assert extract_user_text([]) == ""

    def test_only_system_message(self) -> None:
        assert extract_user_text([{"role": "system", "content": "You are helpful."}]) == ""

    def test_only_assistant_message(self) -> None:
        assert extract_user_text([{"role": "assistant", "content": "Hello!"}]) == ""


class TestStringContent:
    def test_plain_string(self) -> None:
        msgs = [{"role": "user", "content": "hello world"}]
        assert extract_user_text(msgs) == "hello world"

    def test_takes_last_user_turn(self) -> None:
        msgs = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
        ]
        assert extract_user_text(msgs) == "second"

    def test_user_after_system(self) -> None:
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "write me a poem"},
        ]
        assert extract_user_text(msgs) == "write me a poem"

    def test_empty_string_content(self) -> None:
        msgs = [{"role": "user", "content": ""}]
        assert extract_user_text(msgs) == ""


class TestMultimodalContent:
    def test_single_text_part(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [{"type": "text", "text": "describe this image"}],
            }
        ]
        assert extract_user_text(msgs) == "describe this image"

    def test_text_and_image_parts(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is in this picture"},
                    {"type": "image_url", "image_url": {"url": "data:fake"}},
                ],
            }
        ]
        assert extract_user_text(msgs) == "what is in this picture"

    def test_multiple_text_parts_joined(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "text", "text": "world"},
                ],
            }
        ]
        assert extract_user_text(msgs) == "hello world"

    def test_image_only_returns_empty(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": "data:fake"}}],
            }
        ]
        assert extract_user_text(msgs) == ""

    def test_non_dict_parts_ignored(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [
                    "bare string part",
                    {"type": "text", "text": "real part"},
                ],
            }
        ]
        assert extract_user_text(msgs) == "real part"

    def test_multimodal_last_user_turn_wins(self) -> None:
        msgs = [
            {"role": "user", "content": "old plain text"},
            {"role": "assistant", "content": "ok"},
            {
                "role": "user",
                "content": [{"type": "text", "text": "new multimodal"}],
            },
        ]
        assert extract_user_text(msgs) == "new multimodal"


class TestEdgeCases:
    def test_missing_content_key(self) -> None:
        msgs = [{"role": "user"}]
        assert extract_user_text(msgs) == ""

    def test_none_content(self) -> None:
        msgs = [{"role": "user", "content": None}]
        assert extract_user_text(msgs) == ""

    def test_integer_content_ignored(self) -> None:
        # Unexpected type — should not crash and should return ""
        msgs = [{"role": "user", "content": 42}]
        assert extract_user_text(msgs) == ""


# ── LLMResponse ────────────────────────────────────────────────────────────────


class TestLLMResponse:
    def test_empty_raw_gives_empty_content(self) -> None:
        assert LLMResponse({}).content == ""

    def test_extracts_content_from_first_choice(self) -> None:
        raw = {"choices": [{"message": {"content": "hello"}}]}
        assert LLMResponse(raw).content == "hello"

    def test_none_content_normalized_to_empty_string(self) -> None:
        raw = {"choices": [{"message": {"content": None}}]}
        assert LLMResponse(raw).content == ""

    def test_extracts_tool_calls(self) -> None:
        tc = [{"id": "call_1", "function": {"name": "read_file", "arguments": "{}"}}]
        raw = {"choices": [{"message": {"tool_calls": tc}}]}
        assert LLMResponse(raw).tool_calls == tc

    def test_non_list_tool_calls_normalized_to_empty(self) -> None:
        raw = {"choices": [{"message": {"tool_calls": None}}]}
        assert LLMResponse(raw).tool_calls == []

    def test_string_tool_calls_normalized_to_empty(self) -> None:
        raw = {"choices": [{"message": {"tool_calls": "bad"}}]}
        assert LLMResponse(raw).tool_calls == []

    def test_extracts_token_counts(self) -> None:
        raw = {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        resp = LLMResponse(raw)
        assert resp.input_tokens == 10
        assert resp.output_tokens == 5

    def test_missing_usage_gives_zero_tokens(self) -> None:
        resp = LLMResponse({})
        assert resp.input_tokens == 0
        assert resp.output_tokens == 0

    def test_message_is_accessible(self) -> None:
        raw = {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
        assert LLMResponse(raw).message["role"] == "assistant"

    def test_empty_choices_gives_empty_message_and_no_tool_calls(self) -> None:
        resp = LLMResponse({"choices": []})
        assert resp.message == {}
        assert resp.tool_calls == []

    def test_finish_reason_extracted(self) -> None:
        raw = {"choices": [{"finish_reason": "tool_calls", "message": {}}]}
        assert LLMResponse(raw).finish_reason == "tool_calls"

    def test_finish_reason_defaults_to_stop(self) -> None:
        assert LLMResponse({}).finish_reason == "stop"


# ── ToolResult ─────────────────────────────────────────────────────────────────


class TestToolResult:
    def test_short_result_unchanged(self) -> None:
        assert ToolResult("hello").content == "hello"

    def test_long_result_truncated(self) -> None:
        long = "x" * 20_000
        tr = ToolResult(long)
        assert len(tr.content) < len(long)
        assert "truncated" in tr.content

    def test_truncation_suffix_mentions_omitted_bytes(self) -> None:
        long = "x" * 20_000
        tr = ToolResult(long)
        assert "bytes omitted" in tr.content

    def test_non_string_raw_is_stringified(self) -> None:
        tr = ToolResult({"key": "value"})
        assert "key" in tr.content

    def test_custom_max_bytes(self) -> None:
        tr = ToolResult("abcdefgh", max_bytes=4)
        assert tr.content.startswith("abcd")
        assert "truncated" in tr.content

    def test_str_conversion(self) -> None:
        assert str(ToolResult("hello")) == "hello"

    def test_exactly_at_limit_is_not_truncated(self) -> None:
        s = "x" * 16_384
        assert ToolResult(s).content == s

    def test_one_over_limit_is_truncated(self) -> None:
        s = "x" * 16_385
        assert "truncated" in ToolResult(s).content
