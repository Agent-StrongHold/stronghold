"""Helpers for extracting content from OpenAI-format message lists."""

from __future__ import annotations

from typing import Any


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
