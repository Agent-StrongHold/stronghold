"""Helpers for working with OpenAI-format messages and LLM responses."""

from __future__ import annotations

from typing import Any, cast

_MAX_TOOL_RESULT_BYTES = 16_384


class LLMResponse:
    """Typed view over a raw LiteLLM response dict.

    Eliminates the repeated choices[0].message.get() chains across strategies.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    @property
    def _first_choice(self) -> dict[str, Any]:
        choices = cast("list[Any]", self._raw.get("choices") or [])
        return cast("dict[str, Any]", choices[0]) if choices else {}

    @property
    def message(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._first_choice.get("message") or {})

    @property
    def content(self) -> str:
        return cast("str", self.message.get("content") or "")

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        tc = self.message.get("tool_calls")
        return cast("list[dict[str, Any]]", tc) if isinstance(tc, list) else []

    @property
    def finish_reason(self) -> str:
        return cast("str", self._first_choice.get("finish_reason") or "stop")

    @property
    def input_tokens(self) -> int:
        usage = cast("dict[str, Any]", self._raw.get("usage") or {})
        return int(cast("int", usage.get("prompt_tokens", 0)))

    @property
    def output_tokens(self) -> int:
        usage = cast("dict[str, Any]", self._raw.get("usage") or {})
        return int(cast("int", usage.get("completion_tokens", 0)))


class ToolResult:
    """Wraps a raw tool result with automatic truncation to prevent context exhaustion."""

    __slots__ = ("_content",)

    def __init__(self, raw: Any, max_bytes: int = _MAX_TOOL_RESULT_BYTES) -> None:
        s = raw if isinstance(raw, str) else str(raw)
        if len(s) > max_bytes:
            omitted = len(s) - max_bytes
            s = s[:max_bytes] + f"\n[... truncated, {omitted} bytes omitted]"
        self._content = s

    @property
    def content(self) -> str:
        return self._content

    def __str__(self) -> str:
        return self._content


def extract_user_text(messages: list[dict[str, Any]]) -> str:
    """Return the last user-turn text, multimodal-aware.

    Scans messages in reverse to find the last user turn. Handles both
    plain-string content and multimodal content lists (text + image parts).
    Image/non-text parts are silently ignored. Returns "" when no user
    message is present or the content carries no text.
    """
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return ""
    return ""
