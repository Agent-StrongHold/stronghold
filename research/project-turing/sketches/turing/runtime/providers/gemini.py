"""Gemini free-tier provider client.

Uses httpx synchronously (runs inside ThreadPoolExecutor workers per the
runtime's blocking-tick model — see runtime/reactor.py).

Gemini's free tier exposes per-minute RPM caps; tokens-per-minute is tracked
locally by the `FreeTierQuotaTracker` via `record_usage()` callbacks.

References:
    https://ai.google.dev/gemini-api/docs
    https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .base import (
    FreeTierWindow,
    ProviderUnavailable,
    RateLimited,
)


logger = logging.getLogger("turing.providers.gemini")


DEFAULT_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL: str = "gemini-2.0-flash-exp"
# Free-tier caps vary; conservative defaults. Operators should override from
# provider documentation for their region/tier.
DEFAULT_WINDOW_DURATION: timedelta = timedelta(seconds=60)
DEFAULT_TOKENS_ALLOWED_PER_WINDOW: int = 1_000_000


class GeminiProvider:
    name: str = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        window_duration: timedelta = DEFAULT_WINDOW_DURATION,
        tokens_allowed_per_window: int = DEFAULT_TOKENS_ALLOWED_PER_WINDOW,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("GeminiProvider requires a non-empty api_key")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._window_duration = window_duration
        self._tokens_allowed = tokens_allowed_per_window
        self._client = client or httpx.Client(timeout=30.0)
        self._window_started_at: datetime = datetime.now(UTC)
        self._tokens_used: int = 0

    def complete(self, prompt: str, *, max_tokens: int = 512) -> str:
        url = f"{self._base_url}/models/{self._model}:generateContent"
        params = {"key": self._api_key}
        body: dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]},
            ],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.8,
            },
        }
        try:
            response = self._client.post(url, params=params, json=body)
        except httpx.RequestError as exc:
            raise ProviderUnavailable(f"gemini request error: {exc}") from exc

        if response.status_code == 429:
            raise RateLimited("gemini returned 429")
        if 500 <= response.status_code < 600:
            # One retry; then surface.
            try:
                retry = self._client.post(url, params=params, json=body)
            except httpx.RequestError as exc:
                raise ProviderUnavailable(f"gemini retry error: {exc}") from exc
            if not retry.is_success:
                raise ProviderUnavailable(
                    f"gemini {retry.status_code}: {retry.text[:200]}"
                )
            response = retry
        if not response.is_success:
            raise ProviderUnavailable(
                f"gemini {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        text = _extract_text(data)
        self._record_usage(prompt, text, max_tokens)
        return text

    def quota_window(self) -> FreeTierWindow | None:
        now = datetime.now(UTC)
        if now - self._window_started_at >= self._window_duration:
            self._window_started_at = now
            self._tokens_used = 0
        return FreeTierWindow(
            provider=self.name,
            window_kind="rpm",
            window_started_at=self._window_started_at,
            window_duration=self._window_duration,
            tokens_allowed=self._tokens_allowed,
            tokens_used=self._tokens_used,
        )

    def _record_usage(self, prompt: str, reply: str, max_tokens: int) -> None:
        # Cheap char-based estimate. Gemini response's `usageMetadata` has exact
        # counts — upgrade to those once we've verified response shape in
        # a real integration test.
        tokens_used = (len(prompt) + len(reply)) // 4
        self._tokens_used += tokens_used

    def close(self) -> None:
        self._client.close()


def _extract_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if isinstance(text, str):
                return text
    return ""
