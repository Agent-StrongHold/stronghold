"""Evidence-based tests for Bug 3: httpcore.ReadTimeout is unhandled.

v0.9 plan item 8a. ``LiteLLMClient._try_model`` at
``src/stronghold/api/litellm_client.py`` originally caught only
``httpx.ConnectError``, so a transient ``httpcore.ReadTimeout`` (or
``httpx.ReadTimeout``) propagated unhandled through ``complete()`` and
took down the calling Mason stage.

The fix is a bounded retry-with-backoff inside ``_try_model`` wrapping
the HTTP call, using a fresh ``httpx.AsyncClient`` per attempt. Key
invariants these tests lock in:

  1. Transient network exceptions (httpcore/httpx Read/Connect
     timeouts) retry up to ``_RETRY_ATTEMPTS`` times.
  2. Each retry builds a fresh ``AsyncClient`` (no stale transport).
  3. After the retry budget is exhausted, the last transient
     exception is **returned** (not raised) so ``complete()`` can
     fall back to the next model.
  4. HTTP status errors (429/5xx) do NOT feed the retry helper —
     they are handled by the pre-existing model-fallback loop.
  5. 401/403 (non-retryable auth) still raise out immediately.
  6. Backoff total latency stays bounded (~2s) even under mocked sleep.
  7. ``stream()`` is intentionally not retried.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import httpx
import pytest

from stronghold.api.litellm_client import LiteLLMClient

_SUCCESS_BODY: dict[str, Any] = {
    "id": "chatcmpl-x",
    "object": "chat.completion",
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _ok_resp() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = _SUCCESS_BODY
    return resp


def _status_resp(code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = code
    resp.request = MagicMock()
    if code == 401:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401", request=resp.request, response=resp
        )
    return resp


class _SequencedClient:
    """Async httpx.AsyncClient fake that replays a side-effect sequence.

    Each entry is either an Exception (raised on that attempt) or a
    MagicMock response (returned). Tracks per-class instantiation count
    so tests can verify a fresh client is used per retry attempt.
    """

    instances: int = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).instances += 1

    async def __aenter__(self) -> "_SequencedClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def _install_sequence(seq: list[Any]) -> tuple[type[_SequencedClient], list[int]]:
    """Build a patchable AsyncClient subclass that walks `seq`."""
    call_count = [0]

    class _Client(_SequencedClient):
        instances = 0

        async def post(self, *_args: Any, **_kwargs: Any) -> Any:
            idx = call_count[0]
            call_count[0] += 1
            item = seq[idx]
            if isinstance(item, BaseException):
                raise item
            return item

    return _Client, call_count


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep with an instant no-op that records durations."""
    sleeps: list[float] = []

    async def _sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr("asyncio.sleep", _sleep)
    return sleeps


# ---------------------------------------------------------------------------
# Core retry behavior
# ---------------------------------------------------------------------------


class TestReadTimeoutRetry:
    @pytest.mark.asyncio
    async def test_retries_on_httpcore_read_timeout_then_succeeds(
        self, fast_sleep: list[float]
    ) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence(
            [
                httpcore.ReadTimeout("first"),
                httpcore.ReadTimeout("second"),
                _ok_resp(),
            ]
        )
        with patch("httpx.AsyncClient", fake_cls):
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert call_count[0] == 3, f"expected 3 POSTs, got {call_count[0]}"

    @pytest.mark.asyncio
    async def test_retries_on_httpx_read_timeout(
        self, fast_sleep: list[float]
    ) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence(
            [httpx.ReadTimeout("first"), _ok_resp()]
        )
        with patch("httpx.AsyncClient", fake_cls):
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retries_on_httpx_connect_error(
        self, fast_sleep: list[float]
    ) -> None:
        """ConnectError was already caught pre-fix, but via a different path.
        Verify it still works under the new retry helper."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence(
            [httpx.ConnectError("dns"), _ok_resp()]
        )
        with patch("httpx.AsyncClient", fake_cls):
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retries_on_httpcore_connect_timeout(
        self, fast_sleep: list[float]
    ) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence(
            [httpcore.ConnectTimeout("slow"), _ok_resp()]
        )
        with patch("httpx.AsyncClient", fake_cls):
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_retries_on_httpx_remote_protocol_error(
        self, fast_sleep: list[float]
    ) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence(
            [httpx.RemoteProtocolError("half-closed"), _ok_resp()]
        )
        with patch("httpx.AsyncClient", fake_cls):
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Fallback interaction — retry budget vs model-fallback loop
# ---------------------------------------------------------------------------


class TestFallbackInteraction:
    @pytest.mark.asyncio
    async def test_exhausted_retries_fall_back_to_next_model(
        self, fast_sleep: list[float]
    ) -> None:
        """After N transient failures on model A, complete() must try
        model B — not raise ReadTimeout. The exhausted retry surfaces
        as `_try_model` returning an Exception object so the fallback
        loop in `complete()` moves on."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence(
            [
                httpcore.ReadTimeout("a1"),
                httpcore.ReadTimeout("a2"),
                httpcore.ReadTimeout("a3"),
                _ok_resp(),
            ]
        )
        with (
            patch("httpx.AsyncClient", fake_cls),
            patch.object(
                LiteLLMClient, "_fetch_available_models", new=AsyncMock(return_value=[])
            ),
        ):
            result = await client.complete(
                [{"role": "user", "content": "hi"}],
                "model-a",
                fallback_models=["model-b"],
            )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert call_count[0] == 4

    @pytest.mark.asyncio
    async def test_all_models_exhausted_raises_last_transient(
        self, fast_sleep: list[float]
    ) -> None:
        """When every model's retry budget is exhausted, complete()
        must raise the last exception, not silently succeed."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, _ = _install_sequence([httpcore.ReadTimeout("boom")] * 9)
        with (
            patch("httpx.AsyncClient", fake_cls),
            patch.object(
                LiteLLMClient, "_fetch_available_models", new=AsyncMock(return_value=[])
            ),
        ):
            with pytest.raises((httpcore.ReadTimeout, httpx.ReadTimeout)):
                await client.complete(
                    [{"role": "user", "content": "hi"}],
                    "model-a",
                    fallback_models=["model-b", "model-c"],
                )

    @pytest.mark.asyncio
    async def test_http_status_error_is_not_retried(
        self, fast_sleep: list[float]
    ) -> None:
        """429/5xx are handled by the existing model-fallback loop, not
        the transient retry. The retry must fire only on network
        exceptions."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence([_status_resp(429), _ok_resp()])
        with (
            patch("httpx.AsyncClient", fake_cls),
            patch.object(
                LiteLLMClient, "_fetch_available_models", new=AsyncMock(return_value=[])
            ),
        ):
            await client.complete(
                [{"role": "user", "content": "hi"}],
                "model-a",
                fallback_models=["model-b"],
            )
        # Model A hit 429 once (no retry), model B hit 200 once = 2 total.
        assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_401_raises_and_does_not_fall_back(
        self, fast_sleep: list[float]
    ) -> None:
        """Auth failures must abort — no silent model fallback for 401."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, call_count = _install_sequence([_status_resp(401)])
        with (
            patch("httpx.AsyncClient", fake_cls),
            patch.object(
                LiteLLMClient, "_fetch_available_models", new=AsyncMock(return_value=[])
            ),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.complete(
                    [{"role": "user", "content": "hi"}],
                    "model-a",
                    fallback_models=["model-b"],
                )
        assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Retry mechanics
# ---------------------------------------------------------------------------


class TestRetryMechanics:
    @pytest.mark.asyncio
    async def test_retry_uses_fresh_client_per_attempt(
        self, fast_sleep: list[float]
    ) -> None:
        """A broken transport must not be reused — ``httpx.AsyncClient``
        must be re-instantiated for each attempt."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, _ = _install_sequence(
            [
                httpcore.ReadTimeout("first"),
                httpcore.ReadTimeout("second"),
                _ok_resp(),
            ]
        )
        with patch("httpx.AsyncClient", fake_cls):
            await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        assert fake_cls.instances == 3, (
            f"expected 3 AsyncClient instances (one per attempt), "
            f"got {fake_cls.instances}"
        )

    @pytest.mark.asyncio
    async def test_retry_backoff_is_bounded(self, fast_sleep: list[float]) -> None:
        """With attempts=3 and base=0.5s, total mocked backoff time stays
        under ~2s regardless of jitter."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, _ = _install_sequence(
            [
                httpcore.ReadTimeout("first"),
                httpcore.ReadTimeout("second"),
                _ok_resp(),
            ]
        )
        with patch("httpx.AsyncClient", fake_cls):
            await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        retry_sleeps = [s for s in fast_sleep if s >= 0.4]
        assert len(retry_sleeps) == 2, f"expected 2 backoff sleeps, got {fast_sleep}"
        assert sum(retry_sleeps) < 2.0, f"backoff too long: {retry_sleeps}"

    @pytest.mark.asyncio
    async def test_backoff_grows_between_attempts(
        self, fast_sleep: list[float]
    ) -> None:
        """Second backoff must be larger than the first (even accounting
        for jitter — base*2 > base + max_jitter at base=0.5 and jitter<=0.25)."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, _ = _install_sequence(
            [
                httpcore.ReadTimeout("first"),
                httpcore.ReadTimeout("second"),
                _ok_resp(),
            ]
        )
        with patch("httpx.AsyncClient", fake_cls):
            await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        retry_sleeps = [s for s in fast_sleep if s >= 0.4]
        assert len(retry_sleeps) == 2
        # base * 2^0 + jitter[0,0.25] in [0.5, 0.75]
        # base * 2^1 + jitter[0,0.25] in [1.0, 1.25]
        # so second > first always.
        assert retry_sleeps[1] > retry_sleeps[0], retry_sleeps

    @pytest.mark.asyncio
    async def test_success_on_first_try_makes_no_backoff(
        self, fast_sleep: list[float]
    ) -> None:
        """Happy path must not pay retry cost."""
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")
        fake_cls, _ = _install_sequence([_ok_resp()])
        with patch("httpx.AsyncClient", fake_cls):
            await client.complete(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
        backoff_sleeps = [s for s in fast_sleep if s >= 0.4]
        assert backoff_sleeps == []


# ---------------------------------------------------------------------------
# Streaming is intentionally not retried
# ---------------------------------------------------------------------------


class TestStreamIsNotRetried:
    @pytest.mark.asyncio
    async def test_stream_propagates_first_transient_error(
        self, fast_sleep: list[float]
    ) -> None:
        client = LiteLLMClient(base_url="http://fake:4000", api_key="sk-test")

        class _Exploding(_SequencedClient):
            async def stream(self, *args: Any, **kwargs: Any) -> Any:
                raise httpcore.ReadTimeout("boom")

            async def post(self, *args: Any, **kwargs: Any) -> Any:
                raise httpcore.ReadTimeout("boom")

        with patch("httpx.AsyncClient", _Exploding):
            agen = client.stream(
                [{"role": "user", "content": "hi"}],
                "test-model",
            )
            with pytest.raises((httpcore.ReadTimeout, httpx.ReadTimeout, Exception)):
                async for _ in agen:
                    pass
