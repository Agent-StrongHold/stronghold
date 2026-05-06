"""Tests for extract_user_text — the canonical user-turn text extractor."""

from stronghold.agents.messages import extract_user_text


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
