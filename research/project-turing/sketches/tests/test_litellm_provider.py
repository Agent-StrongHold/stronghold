"""Tests for runtime/providers/litellm.py."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from turing.runtime.pools import PoolConfig
from turing.runtime.providers.base import (
    ProviderUnavailable,
    RateLimited,
)
from turing.runtime.providers.litellm import LiteLLMProvider


BASE = "http://litellm.example:4000"


def _pool(
    name: str = "gemini-flash",
    model: str = "gemini/gemini-2.0-flash-exp",
    *,
    window_kind: str = "rpm",
    window_duration_seconds: int = 60,
    tokens_allowed: int = 1_000_000,
    quality_weight: float = 0.7,
) -> PoolConfig:
    return PoolConfig(
        pool_name=name,
        model=model,
        window_kind=window_kind,
        window_duration_seconds=window_duration_seconds,
        tokens_allowed=tokens_allowed,
        quality_weight=quality_weight,
    )


def _reply(text: str, *, total_tokens: int | None = None) -> dict:
    body: dict = {
        "choices": [{"message": {"role": "assistant", "content": text}}],
    }
    if total_tokens is not None:
        body["usage"] = {"total_tokens": total_tokens}
    return body


@respx.mock
def test_complete_happy_path() -> None:
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("hello"))
    )
    provider = LiteLLMProvider(
        pool_config=_pool(),
        base_url=BASE,
        virtual_key="sk-virtual",
    )
    assert provider.complete("hi") == "hello"


@respx.mock
def test_429_raises_rate_limited() -> None:
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(429))
    provider = LiteLLMProvider(
        pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual"
    )
    with pytest.raises(RateLimited):
        provider.complete("x")


@respx.mock
def test_500_retries_once() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(500, text="down"),
            httpx.Response(200, json=_reply("recovered")),
        ]
    )
    provider = LiteLLMProvider(
        pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual"
    )
    assert provider.complete("x") == "recovered"
    assert route.call_count == 2


@respx.mock
def test_500_all_retries_exhausted_raises_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    # New retry logic: 4 total attempts (3 with backoff + 1 final).
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(500, text="down"),
            httpx.Response(500, text="still down"),
            httpx.Response(500, text="still down"),
            httpx.Response(500, text="still down"),
        ]
    )
    provider = LiteLLMProvider(
        pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual"
    )
    with pytest.raises(ProviderUnavailable):
        provider.complete("x")


@respx.mock
def test_request_uses_virtual_key_and_pool_model() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("ok"))
    )
    pool = _pool(name="glm-4-flash", model="openai/glm-4-flash")
    provider = LiteLLMProvider(
        pool_config=pool, base_url=BASE, virtual_key="sk-virtual-xyz"
    )
    provider.complete("hello world", max_tokens=64)

    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer sk-virtual-xyz"
    body = json.loads(request.content.decode())
    assert body["model"] == "openai/glm-4-flash"
    assert body["max_tokens"] == 64
    assert body["messages"] == [{"role": "user", "content": "hello world"}]


@respx.mock
def test_usage_metadata_drives_token_accounting() -> None:
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("ok", total_tokens=2048))
    )
    provider = LiteLLMProvider(
        pool_config=_pool(tokens_allowed=10_000),
        base_url=BASE,
        virtual_key="sk-virtual",
    )
    provider.complete("x")
    window = provider.quota_window()
    assert window is not None
    assert window.tokens_used == 2048


@respx.mock
def test_quota_window_carries_pool_kind() -> None:
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("ok"))
    )
    pool = _pool(name="glm-4", window_kind="rolling_hours", window_duration_seconds=18000)
    provider = LiteLLMProvider(
        pool_config=pool, base_url=BASE, virtual_key="sk-virtual"
    )
    window = provider.quota_window()
    assert window is not None
    assert window.window_kind == "rolling_hours"
    assert window.provider == "glm-4"


def test_missing_virtual_key_raises() -> None:
    with pytest.raises(ValueError, match="virtual_key"):
        LiteLLMProvider(pool_config=_pool(), base_url=BASE, virtual_key="")


def test_missing_base_url_raises() -> None:
    with pytest.raises(ValueError, match="base_url"):
        LiteLLMProvider(pool_config=_pool(), base_url="", virtual_key="sk-virtual")


# ---- Retry / backoff / quota tests ----------------------------------------


@respx.mock
def test_500_retries_up_to_three_times(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    route = respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json=_reply("ok-on-third")),
        ]
    )
    provider = LiteLLMProvider(pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual")
    assert provider.complete("x") == "ok-on-third"
    assert route.call_count == 3


@respx.mock
def test_500_exhausted_raises_and_charges_failure_tokens(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(500),  # would be attempt 4; should never be reached
        ]
    )
    provider = LiteLLMProvider(
        pool_config=_pool(tokens_allowed=10_000), base_url=BASE, virtual_key="sk-virtual"
    )
    with pytest.raises(ProviderUnavailable):
        provider.complete("hello")
    window = provider.quota_window()
    assert window is not None
    # Failure tokens should be non-zero after exhausted retries.
    assert window.tokens_used > 0


@respx.mock
def test_429_charges_failure_tokens() -> None:
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(429))
    provider = LiteLLMProvider(
        pool_config=_pool(tokens_allowed=10_000), base_url=BASE, virtual_key="sk-virtual"
    )
    with pytest.raises(RateLimited):
        provider.complete("hello world")
    window = provider.quota_window()
    assert window is not None
    assert window.tokens_used > 0


@respx.mock
def test_429_parses_retry_after_header() -> None:
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "42"})
    )
    provider = LiteLLMProvider(pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual")
    with pytest.raises(RateLimited, match="retry-after=42"):
        provider.complete("x")


@respx.mock
def test_complete_chat_sends_system_role() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("response"))
    )
    provider = LiteLLMProvider(pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual")
    result = provider.complete_chat(
        system="You are an agent.",
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result == "response"
    body = json.loads(route.calls.last.request.content.decode())
    msgs = body["messages"]
    assert msgs[0] == {"role": "system", "content": "You are an agent."}
    assert msgs[1] == {"role": "user", "content": "hello"}


@respx.mock
def test_complete_chat_default_max_tokens() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("ok"))
    )
    provider = LiteLLMProvider(pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual")
    provider.complete_chat(system="sys", messages=[{"role": "user", "content": "q"}])
    body = json.loads(route.calls.last.request.content.decode())
    assert body.get("max_tokens") == 800


@respx.mock
def test_complete_chat_multi_turn_preserves_order() -> None:
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_reply("ok"))
    )
    provider = LiteLLMProvider(pool_config=_pool(), base_url=BASE, virtual_key="sk-virtual")
    provider.complete_chat(
        system="sys",
        messages=[
            {"role": "user", "content": "turn1"},
            {"role": "assistant", "content": "reply1"},
            {"role": "user", "content": "turn2"},
        ],
    )
    body = json.loads(route.calls.last.request.content.decode())
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "user"]
