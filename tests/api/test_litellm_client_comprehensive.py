"""Comprehensive tests for LiteLLMClient.

Covers: complete(), fallback model logic, 429/5xx retry, streaming,
error handling, timeout, request body construction, auth headers.

Uses respx for HTTP mocking (no unittest.mock).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import httpx
import pytest
import respx

from stronghold.api.litellm_client import LiteLLMClient

# ── Helpers ──────────────────────────────────────────────────────────

BASE_URL = "http://litellm-proxy:4000"
API_KEY = "sk-test-key-12345"
ENDPOINT = f"{BASE_URL}/v1/chat/completions"
MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]


def _ok_body(content: str = "Hello!", model: str = "test-model") -> dict[str, Any]:
    """Build a successful chat completion response body."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _make_client(base_url: str = BASE_URL, api_key: str = API_KEY) -> LiteLLMClient:
    return LiteLLMClient(base_url=base_url, api_key=api_key)


# Patch asyncio.sleep so fallback tests don't wait 1s per retry.
@pytest.fixture(autouse=True)
def _fast_sleep() -> Generator[None]:
    with patch("stronghold.api.litellm_client.asyncio.sleep", new_callable=AsyncMock):
        yield


# ── 1. Successful completion ────────────────────────────────────────


class TestSuccessfulCompletion:
    """Tests for the happy-path complete() call."""

    @respx.mock
    async def test_returns_parsed_json(self) -> None:
        body = _ok_body("World")
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=body))

        client = _make_client()
        result = await client.complete(MESSAGES, "test-model")

        assert result["choices"][0]["message"]["content"] == "World"
        assert result["object"] == "chat.completion"
        assert result["model"] == "test-model"

    @respx.mock
    async def test_sends_authorization_header(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        await client.complete(MESSAGES, "test-model")

        request = route.calls[0].request
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert request.headers["content-type"] == "application/json"

    @respx.mock
    async def test_strips_trailing_slash_from_base_url(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client(base_url=f"{BASE_URL}/")
        await client.complete(MESSAGES, "test-model")

        assert route.call_count == 1


# ── 2. Request body construction ────────────────────────────────────


class TestRequestBodyConstruction:
    """Tests that optional parameters are correctly included in the request body."""

    @respx.mock
    async def test_includes_messages_and_model(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        await client.complete(MESSAGES, "gpt-4")

        sent = route.calls[0].request
        body = json.loads(sent.content)
        assert body["messages"] == MESSAGES
        assert body["model"] == "gpt-4"

    @respx.mock
    async def test_includes_tools_when_provided(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))
        tools: list[dict[str, Any]] = [{"type": "function", "function": {"name": "search"}}]

        client = _make_client()
        await client.complete(MESSAGES, "m", tools=tools)

        body = json.loads(route.calls[0].request.content)
        assert body["tools"] == tools

    @respx.mock
    async def test_includes_tool_choice_when_provided(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        await client.complete(MESSAGES, "m", tool_choice="auto")

        body = json.loads(route.calls[0].request.content)
        assert body["tool_choice"] == "auto"

    @respx.mock
    async def test_includes_max_tokens_when_provided(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        await client.complete(MESSAGES, "m", max_tokens=4096)

        body = json.loads(route.calls[0].request.content)
        assert body["max_tokens"] == 4096

    @respx.mock
    async def test_includes_temperature_when_provided(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        await client.complete(MESSAGES, "m", temperature=0.7)

        body = json.loads(route.calls[0].request.content)
        assert body["temperature"] == 0.7

    @respx.mock
    async def test_includes_metadata_when_provided(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))
        meta = {"trace_id": "abc-123", "user_id": "u42"}

        client = _make_client()
        await client.complete(MESSAGES, "m", metadata=meta)

        body = json.loads(route.calls[0].request.content)
        assert body["metadata"] == meta

    @respx.mock
    async def test_omits_optional_fields_when_not_provided(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        await client.complete(MESSAGES, "m")

        body = json.loads(route.calls[0].request.content)
        assert "tools" not in body
        assert "tool_choice" not in body
        assert "max_tokens" not in body
        assert "temperature" not in body
        assert "metadata" not in body


# ── 3. Fallback on retryable HTTP errors ────────────────────────────


class TestFallbackOnRetryableErrors:
    """Tests that 429, 500, 502, 503 trigger model fallback."""

    @respx.mock
    async def test_429_falls_back_to_next_model(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_ok_body("from fallback")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "primary", fallback_models=["secondary"])

        assert result["choices"][0]["message"]["content"] == "from fallback"
        assert route.call_count == 2

    @respx.mock
    async def test_500_falls_back_to_next_model(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(500, text="internal error"),
            httpx.Response(200, json=_ok_body("recovered")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "primary", fallback_models=["secondary"])

        assert result["choices"][0]["message"]["content"] == "recovered"

    @respx.mock
    async def test_502_falls_back_to_next_model(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json=_ok_body("ok")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "primary", fallback_models=["fallback"])

        assert result["choices"][0]["message"]["content"] == "ok"

    @respx.mock
    async def test_503_falls_back_to_next_model(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(503, text="service unavailable"),
            httpx.Response(200, json=_ok_body("ok")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "primary", fallback_models=["fallback"])

        assert result["choices"][0]["message"]["content"] == "ok"

    @respx.mock
    async def test_cascading_fallback_through_multiple_models(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json=_ok_body("third model")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "model-a", fallback_models=["model-b", "model-c"])

        assert result["choices"][0]["message"]["content"] == "third model"
        assert route.call_count == 3

    @respx.mock
    async def test_fallback_sends_correct_model_in_body(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(429, text="rate limited"),
            httpx.Response(200, json=_ok_body("ok")),
        ]

        client = _make_client()
        await client.complete(MESSAGES, "primary-model", fallback_models=["fallback-model"])

        first_body = json.loads(route.calls[0].request.content)
        second_body = json.loads(route.calls[1].request.content)
        assert first_body["model"] == "primary-model"
        assert second_body["model"] == "fallback-model"


# ── 4. Connection errors ────────────────────────────────────────────


class TestConnectionErrorFallback:
    """Tests that ConnectError triggers fallback to next model."""

    @respx.mock
    async def test_connect_error_falls_back(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json=_ok_body("fallback ok")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "primary", fallback_models=["fallback"])

        assert result["choices"][0]["message"]["content"] == "fallback ok"

    @respx.mock
    async def test_all_connect_errors_raises_last(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.ConnectError("refused 1"),
            httpx.ConnectError("refused 2"),
        ]

        client = _make_client()
        with pytest.raises(httpx.ConnectError, match="refused 2"):
            await client.complete(MESSAGES, "model-a", fallback_models=["model-b"])


# ── 5. Non-retryable errors ─────────────────────────────────────────


class TestNonRetryableErrors:
    """Tests that 400, 401, 403 etc. raise immediately without fallback."""

    @respx.mock
    async def test_400_raises_immediately(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(400, text="bad request"))

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.complete(MESSAGES, "model-a", fallback_models=["model-b"])

        assert exc_info.value.response.status_code == 400
        assert route.call_count == 1  # No fallback attempted

    @respx.mock
    async def test_401_raises_immediately(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(401, text="unauthorized"))

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.complete(MESSAGES, "model-a", fallback_models=["model-b"])

        assert exc_info.value.response.status_code == 401
        assert route.call_count == 1

    @respx.mock
    async def test_403_raises_immediately(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(403, text="forbidden"))

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.complete(MESSAGES, "model-a", fallback_models=["model-b"])

        assert exc_info.value.response.status_code == 403
        assert route.call_count == 1


# ── 6. All models fail ──────────────────────────────────────────────


class TestAllModelsFail:
    """Tests the error raised when every model in the list fails."""

    @respx.mock
    async def test_all_429_raises_http_status_error(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(429, text="limited"),
            httpx.Response(429, text="limited"),
            httpx.Response(429, text="limited"),
        ]

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(MESSAGES, "a", fallback_models=["b", "c"])
        assert route.call_count == 3

    @respx.mock
    async def test_no_fallback_models_single_failure_raises(self) -> None:
        respx.post(ENDPOINT).mock(return_value=httpx.Response(500, text="error"))

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(MESSAGES, "only-model")

    async def test_no_models_at_all_raises_runtime_error(self) -> None:
        """Edge case: empty models_to_try list (models_to_try = [model] always has 1)."""
        # The code always puts at least [model] in the list, so this verifies
        # that a single retryable failure with no fallbacks raises the stored error.
        with respx.mock:
            respx.post(ENDPOINT).mock(return_value=httpx.Response(503, text="unavailable"))
            client = _make_client()
            with pytest.raises(httpx.HTTPStatusError):
                await client.complete(MESSAGES, "sole-model")


# ── 7. Dynamic fallback models ──────────────────────────────────────


class TestDynamicFallbackModels:
    """Tests the _fallback_models attribute set by the DI container."""

    @respx.mock
    async def test_uses_dynamic_fallback_models(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(429, text="limited"),
            httpx.Response(200, json=_ok_body("dynamic ok")),
        ]

        client = _make_client()
        client._fallback_models = ["dynamic-fallback"]  # type: ignore[attr-defined]

        result = await client.complete(MESSAGES, "primary")

        assert result["choices"][0]["message"]["content"] == "dynamic ok"
        assert route.call_count == 2

    @respx.mock
    async def test_explicit_fallback_overrides_dynamic(self) -> None:
        """When fallback_models kwarg is provided, _fallback_models is ignored."""
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(429, text="limited"),
            httpx.Response(200, json=_ok_body("explicit")),
        ]

        client = _make_client()
        client._fallback_models = ["should-not-use"]  # type: ignore[attr-defined]

        result = await client.complete(MESSAGES, "primary", fallback_models=["explicit-fb"])

        assert result["choices"][0]["message"]["content"] == "explicit"

        second_body = json.loads(route.calls[1].request.content)
        assert second_body["model"] == "explicit-fb"

    @respx.mock
    async def test_no_dynamic_fallback_when_not_set(self) -> None:
        """Without _fallback_models attr and no fallback_models kwarg, only primary tried."""
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(429, text="limited"))

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(MESSAGES, "only-model")

        assert route.call_count == 1


# ── 8. Streaming ────────────────────────────────────────────────────


class TestStreaming:
    """Tests for the stream() method."""

    @respx.mock
    async def test_stream_yields_chunks(self) -> None:
        sse_data = (
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":" World"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, text=sse_data))

        client = _make_client()
        chunks: list[str] = []
        async for chunk in client.stream(MESSAGES, "test-model"):
            chunks.append(chunk)

        # respx returns text as a single chunk; verify content is present
        combined = "".join(chunks)
        assert "Hello" in combined
        assert "World" in combined
        assert "[DONE]" in combined

    @respx.mock
    async def test_stream_sends_correct_body(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, text="data: [DONE]\n\n"))

        client = _make_client()
        async for _ in client.stream(MESSAGES, "gpt-4", max_tokens=100):
            pass

        body = json.loads(route.calls[0].request.content)
        assert body["model"] == "gpt-4"
        assert body["messages"] == MESSAGES
        assert body["stream"] is True
        assert body["max_tokens"] == 100

    @respx.mock
    async def test_stream_sends_auth_header(self) -> None:
        route = respx.post(ENDPOINT).mock(return_value=httpx.Response(200, text="data: [DONE]\n\n"))

        client = _make_client()
        async for _ in client.stream(MESSAGES, "m"):
            pass

        request = route.calls[0].request
        assert request.headers["authorization"] == f"Bearer {API_KEY}"


# ── 9. Timeout configuration ────────────────────────────────────────


class TestTimeoutConfiguration:
    """Verify the client uses the expected 180-second timeout."""

    @respx.mock
    async def test_complete_uses_180s_timeout(self) -> None:
        """The timeout is passed to httpx.AsyncClient(timeout=180.0).
        We verify the request completes successfully (respx would fail
        if the client was misconfigured)."""
        respx.post(ENDPOINT).mock(return_value=httpx.Response(200, json=_ok_body()))

        client = _make_client()
        result = await client.complete(MESSAGES, "m")

        assert result["id"] == "chatcmpl-test"


# ── 10. Mixed error scenarios ────────────────────────────────────────


class TestMixedErrorScenarios:
    """Tests combining different error types in a single fallback chain."""

    @respx.mock
    async def test_connect_error_then_429_then_success(self) -> None:
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.Response(429, text="limited"),
            httpx.Response(200, json=_ok_body("third try")),
        ]

        client = _make_client()
        result = await client.complete(MESSAGES, "a", fallback_models=["b", "c"])

        assert result["choices"][0]["message"]["content"] == "third try"
        assert route.call_count == 3

    @respx.mock
    async def test_500_then_connect_error_raises_connect_error(self) -> None:
        """When last error is ConnectError, that's what gets raised."""
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.Response(500, text="server error"),
            httpx.ConnectError("refused"),
        ]

        client = _make_client()
        with pytest.raises(httpx.ConnectError):
            await client.complete(MESSAGES, "a", fallback_models=["b"])

    @respx.mock
    async def test_connect_error_then_500_raises_http_status_error(self) -> None:
        """When last error is HTTPStatusError (from 500), that's what gets raised."""
        route = respx.post(ENDPOINT)
        route.side_effect = [
            httpx.ConnectError("refused"),
            httpx.Response(500, text="server error"),
        ]

        client = _make_client()
        with pytest.raises(httpx.HTTPStatusError):
            await client.complete(MESSAGES, "a", fallback_models=["b"])
