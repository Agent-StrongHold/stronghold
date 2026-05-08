"""LiteLLM-backed Provider — single client, many pools.

The operator runs LiteLLM with their providers (Google, z.ai, OpenRouter, …)
already configured. Project Turing connects with a single virtual key and
routes by model name. One LiteLLMProvider per pool: the pool's `model`
field tells LiteLLM which backend to invoke.

LiteLLM exposes an OpenAI-compatible `/chat/completions` endpoint, so the
request shape is the same regardless of which underlying provider serves
the model.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from ..pools import PoolConfig
from .base import (
    FreeTierWindow,
    ProviderUnavailable,
    RateLimited,
)


logger = logging.getLogger("turing.providers.litellm")

# Exponential-backoff delays for 5xx retries (seconds between attempts 1→2, 2→3, 3→fail).
_RETRY_DELAYS = (0.5, 1.0, 2.0)


class LiteLLMProvider:
    """One pool's worth of LiteLLM access."""

    def __init__(
        self,
        *,
        pool_config: PoolConfig,
        base_url: str,
        virtual_key: str,
        client: httpx.Client | None = None,
    ) -> None:
        if not virtual_key:
            raise ValueError("LiteLLMProvider requires a non-empty virtual_key")
        if not base_url:
            raise ValueError("LiteLLMProvider requires a non-empty base_url")
        self._pool_config = pool_config
        self.name = pool_config.pool_name
        self._model = pool_config.model
        self._base_url = base_url.rstrip("/")
        self._virtual_key = virtual_key
        self._client = client or httpx.Client(timeout=90.0)

        self._window_started_at: datetime = datetime.now(UTC)
        self._window_duration: timedelta = timedelta(seconds=pool_config.window_duration_seconds)
        self._tokens_allowed: int = pool_config.tokens_allowed
        self._tokens_used: int = 0
        # Tracks tokens estimated on failed requests (5xx exhausted, 429).
        # Added to _tokens_used so quota pressure rises under failures.
        self._failure_tokens: int = 0

    def complete(self, prompt: str, *, max_tokens: int | None = None) -> str:
        """Single-turn completion: wraps the prompt as a user message."""
        messages = [{"role": "user", "content": prompt}]
        prompt_len = len(prompt)
        return self._do_chat(messages, max_tokens=max_tokens, prompt_len_hint=prompt_len)

    def complete_chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 800,
    ) -> str:
        """Multi-turn chat completion with a system prompt and role-split messages.

        ``messages`` is a list of ``{"role": "user"|"assistant", "content": str}``
        dicts in chronological order. The system prompt is prepended as a
        ``{"role": "system", ...}`` message.
        """
        full_messages = [{"role": "system", "content": system}, *messages]
        prompt_len = sum(len(m.get("content", "")) for m in full_messages)
        return self._do_chat(full_messages, max_tokens=max_tokens, prompt_len_hint=prompt_len)

    def _do_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None,
        prompt_len_hint: int = 0,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._virtual_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.8,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        last_exc: Exception | None = None
        for attempt, delay in enumerate((*_RETRY_DELAYS, None)):
            try:
                response = self._client.post(url, headers=headers, json=body)
            except httpx.RequestError as exc:
                raise ProviderUnavailable(
                    f"litellm[{self._model}] request error: {exc}"
                ) from exc

            if response.status_code == 429:
                retry_after = _parse_retry_after(response)
                self._failure_tokens += max(prompt_len_hint // 4, 1)
                raise RateLimited(
                    f"litellm[{self._model}] 429 (retry-after={retry_after}s)"
                )

            if 500 <= response.status_code < 600:
                last_exc = ProviderUnavailable(
                    f"litellm[{self._model}] {response.status_code}: "
                    "<response body sanitized>"
                )
                if delay is not None:
                    logger.warning(
                        "litellm[%s] %d on attempt %d, retrying in %.1fs",
                        self._model,
                        response.status_code,
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                # Final attempt failed — record the failure tokens.
                self._failure_tokens += max(prompt_len_hint // 4, 1)
                raise last_exc

            if not response.is_success:
                raise ProviderUnavailable(
                    f"litellm[{self._model}] {response.status_code}: "
                    "<response body sanitized>"
                )

            data = response.json()
            text = _extract_text(data)
            usage = data.get("usage") or {}
            tokens_used = int(usage.get("total_tokens", 0)) or (
                (prompt_len_hint + len(text)) // 4
            )
            self._tokens_used += tokens_used
            return text

        # Should be unreachable; last_exc is always set when we reach here.
        raise last_exc or ProviderUnavailable(f"litellm[{self._model}] all retries exhausted")

    def embed(self, text: str) -> list[float]:
        """Call LiteLLM /v1/embeddings. Uses this pool's model.

        For embedding pools (role='embedding'), the operator configures
        an embedding model (e.g., `ollama/nomic-embed-text`). For chat
        pools, this will probably fail — catch the ProviderUnavailable
        and route embeddings through a dedicated embedding pool instead.
        """
        url = f"{self._base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self._virtual_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "input": text,
        }
        try:
            response = self._client.post(url, headers=headers, json=body)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"litellm[{self._model}] embed error: {exc}") from exc
        if response.status_code == 429:
            raise RateLimited(f"litellm[{self._model}] embed 429")
        if not response.is_success:
            raise ProviderUnavailable(
                f"litellm[{self._model}] embed {response.status_code}: <response body sanitized>"
            )
        data = response.json()
        # OpenAI-compat shape: {"data": [{"embedding": [...], ...}], "usage": ...}
        items = data.get("data") or []
        if not items or "embedding" not in items[0]:
            raise ProviderUnavailable(f"litellm[{self._model}] embed returned no embedding")
        embedding = items[0]["embedding"]
        usage = data.get("usage") or {}
        tokens_used = int(usage.get("total_tokens", 0)) or (len(text) // 4)
        self._tokens_used += tokens_used
        return list(embedding)

    def generate_image(self, prompt: str) -> str:
        """Call LiteLLM /v1/images/generations. Returns base64-encoded image data."""
        url = f"{self._base_url}/v1/images/generations"
        headers = {
            "Authorization": f"Bearer {self._virtual_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "response_format": "b64_json",
        }
        try:
            response = self._client.post(url, headers=headers, json=body, timeout=60.0)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"litellm[{self._model}] image gen error: {exc}") from exc
        if response.status_code == 429:
            raise RateLimited(f"litellm[{self._model}] image gen 429")
        if not response.is_success:
            raise ProviderUnavailable(
                f"litellm[{self._model}] image gen {response.status_code}: <response body sanitized>"
            )
        data = response.json()
        items = data.get("data") or []
        if not items:
            raise ProviderUnavailable(f"litellm[{self._model}] image gen returned no data")
        b64 = items[0].get("b64_json") or items[0].get("url", "")
        self._tokens_used += len(prompt) // 4
        return b64

    def quota_window(self) -> FreeTierWindow | None:
        now = datetime.now(UTC)
        if now - self._window_started_at >= self._window_duration:
            self._window_started_at = now
            self._tokens_used = 0
            self._failure_tokens = 0
        effective_used = self._tokens_used + self._failure_tokens
        return FreeTierWindow(
            provider=self.name,
            window_kind=self._pool_config.window_kind,
            window_started_at=self._window_started_at,
            window_duration=self._window_duration,
            tokens_allowed=self._tokens_allowed,
            tokens_used=effective_used,
        )

    def close(self) -> None:
        self._client.close()


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    for choice in choices:
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def _parse_retry_after(response: httpx.Response) -> float:
    """Extract Retry-After seconds from a 429 response; default 30."""
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return 30.0
