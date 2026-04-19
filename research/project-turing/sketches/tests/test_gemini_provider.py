"""Tests for runtime/providers/gemini.py with httpx mocked via respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from turing.runtime.providers.base import (
    ProviderUnavailable,
    RateLimited,
)
from turing.runtime.providers.gemini import DEFAULT_BASE_URL, GeminiProvider


def _url(model: str) -> str:
    return f"{DEFAULT_BASE_URL}/models/{model}:generateContent"


def _reply(text: str) -> dict:
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}},
        ]
    }


@respx.mock
def test_complete_happy_path() -> None:
    route = respx.post(_url("gemini-2.0-flash-exp")).mock(
        return_value=httpx.Response(200, json=_reply("hello world"))
    )
    provider = GeminiProvider(api_key="sk-example-xxx")
    result = provider.complete("prompt", max_tokens=128)
    assert result == "hello world"
    assert route.called


@respx.mock
def test_complete_429_raises_rate_limited() -> None:
    respx.post(_url("gemini-2.0-flash-exp")).mock(
        return_value=httpx.Response(429, json={"error": "rate limit"})
    )
    provider = GeminiProvider(api_key="sk-example-xxx")
    with pytest.raises(RateLimited):
        provider.complete("prompt")


@respx.mock
def test_complete_500_retries_once() -> None:
    route = respx.post(_url("gemini-2.0-flash-exp")).mock(
        side_effect=[
            httpx.Response(500, text="server exploded"),
            httpx.Response(200, json=_reply("back online")),
        ]
    )
    provider = GeminiProvider(api_key="sk-example-xxx")
    result = provider.complete("prompt")
    assert result == "back online"
    assert route.call_count == 2


@respx.mock
def test_complete_500_twice_raises_unavailable() -> None:
    respx.post(_url("gemini-2.0-flash-exp")).mock(
        side_effect=[
            httpx.Response(500, text="down"),
            httpx.Response(500, text="still down"),
        ]
    )
    provider = GeminiProvider(api_key="sk-example-xxx")
    with pytest.raises(ProviderUnavailable):
        provider.complete("prompt")


@respx.mock
def test_request_body_shape() -> None:
    route = respx.post(_url("gemini-2.0-flash-exp")).mock(
        return_value=httpx.Response(200, json=_reply("ok"))
    )
    provider = GeminiProvider(api_key="sk-example-xxx")
    provider.complete("question?", max_tokens=64)

    assert route.calls.call_count == 1
    request = route.calls.last.request
    body = request.content.decode()
    import json

    parsed = json.loads(body)
    assert parsed["contents"][0]["parts"][0]["text"] == "question?"
    assert parsed["generationConfig"]["maxOutputTokens"] == 64
    assert request.url.params["key"] == "sk-example-xxx"


def test_api_key_required() -> None:
    with pytest.raises(ValueError, match="api_key"):
        GeminiProvider(api_key="")


@respx.mock
def test_quota_window_updates_on_calls() -> None:
    respx.post(_url("gemini-2.0-flash-exp")).mock(
        return_value=httpx.Response(200, json=_reply("x" * 100))
    )
    provider = GeminiProvider(
        api_key="sk-example-xxx",
        tokens_allowed_per_window=1000,
    )
    before = provider.quota_window()
    assert before is not None
    assert before.tokens_used == 0

    provider.complete("a prompt of some length")
    after = provider.quota_window()
    assert after is not None
    assert after.tokens_used > 0
