"""LiteLLM client: implements LLMClient protocol via httpx.

On 429 or 5xx: tries fallback models from the candidate list.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpcore
import httpx

logger = logging.getLogger("stronghold.llm")

# Transient network errors that should be retried with backoff inside
# _try_model before giving up on a model. These are distinct from HTTP
# status errors (429/5xx), which are handled by the model-fallback loop
# in complete() — 429/5xx indicates a model-specific problem, while the
# exceptions below indicate a transport-level blip that typically clears
# on a fresh connection.
_TRANSIENT_EXCS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpcore.ReadTimeout,
    httpcore.ConnectTimeout,
)

# Retry budget. Tuned for Mason pipelines — 3 attempts with ~0.5s base
# backoff caps total added latency at ~2s even in the worst case, which
# is cheap compared to the alternative (a whole pipeline stage failing
# because a single httpcore.ReadTimeout escaped unhandled).
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5


class LiteLLMClient:
    """Forwards requests to LiteLLM proxy with model fallback on errors."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        metadata: dict[str, Any] | None = None,
        fallback_models: list[str] | None = None,
    ) -> dict[str, Any]:
        """Non-streaming completion with exhaustive model fallback.

        On 429/5xx/400 (cooldown): cycles through explicit fallbacks,
        then fetches ALL available models from LiteLLM and tries each.
        """
        models_to_try = [model]
        if fallback_models:
            models_to_try.extend(fallback_models)
        elif hasattr(self, "_fallback_models") and self._fallback_models:
            models_to_try.extend(self._fallback_models)

        body: dict[str, Any] = {"messages": messages}
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if metadata:
            body["metadata"] = metadata

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        tried: set[str] = set()
        last_error: Exception | None = None

        # Phase 1: try explicit models
        for try_model in models_to_try:
            result = await self._try_model(try_model, body, headers)
            tried.add(try_model)
            if isinstance(result, dict):
                return result
            last_error = result

        # Phase 2: fetch all available models and try each
        available = await self._fetch_available_models(headers)
        for try_model in available:
            if try_model in tried:
                continue
            result = await self._try_model(try_model, body, headers)
            tried.add(try_model)
            if isinstance(result, dict):
                logger.info("Fallback succeeded on model %s (tried %d)", try_model, len(tried))
                return result
            last_error = result

        # All models exhausted
        logger.warning("All %d models exhausted", len(tried))
        if last_error:
            raise last_error
        msg = f"No models available (tried {len(tried)})"
        raise RuntimeError(msg)

    async def _try_model(
        self,
        model: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any] | Exception:
        """Try a single model. Returns response dict on success, Exception on failure.

        Transient network errors (see ``_TRANSIENT_EXCS``) are retried up to
        ``_RETRY_ATTEMPTS`` times with exponential backoff + jitter before
        giving up on this model. A fresh ``httpx.AsyncClient`` is created
        on every attempt because the previous transport may be in a bad
        state. After exhausting retries, the last transient exception is
        **returned** (not raised) so the outer ``complete()`` fallback loop
        can still try the next model.

        Non-retryable HTTP status errors (401, 403, etc.) raise out so
        callers see auth failures immediately. Retryable-via-fallback
        codes (400/422/429/5xx) are returned as ``HTTPStatusError`` so
        the model-fallback loop picks a different model.
        """
        body["model"] = model
        last_transient: BaseException | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=600.0) as client:
                    resp = await client.post(
                        f"{self._base_url}/v1/chat/completions",
                        json=body,
                        headers=headers,
                    )
            except _TRANSIENT_EXCS as exc:
                last_transient = exc
                if attempt == _RETRY_ATTEMPTS:
                    logger.debug(
                        "Model %s exhausted %d retries on %s",
                        model, _RETRY_ATTEMPTS, type(exc).__name__,
                    )
                    return exc
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
                logger.warning(
                    "transient http error on %s attempt %d/%d: %s; sleeping %.2fs",
                    model, attempt, _RETRY_ATTEMPTS, type(exc).__name__, delay,
                )
                await asyncio.sleep(delay)
                continue

            if resp.status_code == 200:  # noqa: PLR2004
                return resp.json()  # type: ignore[no-any-return]

            # Retryable-via-fallback: 429, 400 (cooldown), 422 (model doesn't support tools), 5xx.
            # These don't go through the transient-retry path because they indicate
            # a model-specific problem, not a transport problem — the fallback loop
            # in complete() handles them by trying the next model.
            if resp.status_code in (400, 422, 429, 500, 502, 503):
                logger.debug("Model %s returned %d, skipping", model, resp.status_code)
                await asyncio.sleep(0.2)
                return httpx.HTTPStatusError(
                    f"{resp.status_code}",
                    request=resp.request,
                    response=resp,
                )

            # Non-retryable (401, 403, etc.) — raise out so callers see auth failures.
            resp.raise_for_status()
            # Unreachable: raise_for_status() always raises on non-2xx; kept
            # only to satisfy the type checker that the branch has a return.
            return RuntimeError(f"Unexpected state for model {model}")  # pragma: no cover

        # Loop exited without returning — unreachable in practice: every
        # attempt either returns a dict/exception or hits the transient
        # exhaustion return above. Kept as a type-checker hint.
        assert last_transient is not None  # pragma: no cover
        return last_transient  # pragma: no cover  # type: ignore[return-value]

    async def _fetch_available_models(
        self,
        headers: dict[str, str],
    ) -> list[str]:
        """Fetch all model IDs from LiteLLM /v1/models endpoint."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self._base_url}/v1/models",
                    headers=headers,
                )
            if resp.status_code == 200:  # noqa: PLR2004
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                logger.info("Fetched %d available models for fallback", len(models))
                return models
        except Exception:
            logger.warning("Failed to fetch model list for fallback")
        return []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming completion. Yields SSE chunks."""
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with (
            httpx.AsyncClient(timeout=180.0) as client,
            client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=body,
                headers=headers,
            ) as resp,
        ):
            async for chunk in resp.aiter_text():
                yield chunk
