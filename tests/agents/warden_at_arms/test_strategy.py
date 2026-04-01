"""Tests for WardenAtArmsStrategy — API discovery + risk classification."""

from __future__ import annotations

from typing import Any

from stronghold.agents.warden_at_arms.strategy import (
    WardenAtArmsStrategy,
    classify_endpoint,
    discover_api,
)
from stronghold.types.agent import ReasoningResult
from tests.fakes import FakeLLMClient


def _llm_response(content: str) -> dict[str, object]:
    """Build a FakeLLMClient-compatible response dict."""
    return {
        "id": "chatcmpl-warden",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


# ── Sample OpenAPI-like specs ────────────────────────────────────────

SIMPLE_SPEC: dict[str, Any] = {
    "paths": {
        "/users": {
            "get": {"summary": "List users"},
        },
        "/users/{id}": {
            "get": {"summary": "Get user by ID"},
            "put": {"summary": "Update user"},
            "delete": {"summary": "Delete user"},
        },
        "/health": {
            "get": {"summary": "Health check"},
        },
    },
}

MIXED_METHODS_SPEC: dict[str, Any] = {
    "paths": {
        "/items": {
            "get": {"summary": "List items"},
            "post": {"summary": "Create item"},
        },
        "/items/{id}": {
            "patch": {"summary": "Partial update item"},
            "delete": {"summary": "Remove item"},
        },
        "/items/{id}/archive": {
            "post": {"summary": "Archive item"},
        },
    },
}

EMPTY_SPEC: dict[str, Any] = {"paths": {}}

NO_PATHS_SPEC: dict[str, Any] = {"info": {"title": "No paths API"}}


# ── classify_endpoint tests ──────────────────────────────────────────


class TestClassifyEndpoint:
    """Unit tests for classify_endpoint(method, path) -> risk level."""

    def test_get_is_low(self) -> None:
        assert classify_endpoint("GET", "/users") == "low"

    def test_head_is_low(self) -> None:
        assert classify_endpoint("HEAD", "/users") == "low"

    def test_options_is_low(self) -> None:
        assert classify_endpoint("OPTIONS", "/users") == "low"

    def test_post_is_medium(self) -> None:
        assert classify_endpoint("POST", "/items") == "medium"

    def test_put_is_medium(self) -> None:
        assert classify_endpoint("PUT", "/users/1") == "medium"

    def test_patch_is_medium(self) -> None:
        assert classify_endpoint("PATCH", "/users/1") == "medium"

    def test_delete_is_high(self) -> None:
        assert classify_endpoint("DELETE", "/users/1") == "high"

    def test_case_insensitive_method(self) -> None:
        assert classify_endpoint("get", "/users") == "low"
        assert classify_endpoint("Delete", "/items/1") == "high"
        assert classify_endpoint("post", "/items") == "medium"

    def test_destructive_path_keywords_elevate_risk(self) -> None:
        """Paths with destructive keywords elevate POST/PUT to high risk."""
        assert classify_endpoint("POST", "/users/purge") == "high"
        assert classify_endpoint("POST", "/data/destroy") == "high"
        assert classify_endpoint("POST", "/items/drop") == "high"
        assert classify_endpoint("PUT", "/system/reset") == "high"
        assert classify_endpoint("POST", "/db/truncate") == "high"

    def test_unknown_method_defaults_to_medium(self) -> None:
        assert classify_endpoint("TRACE", "/debug") == "medium"
        assert classify_endpoint("CONNECT", "/proxy") == "medium"


# ── discover_api tests ───────────────────────────────────────────────


class TestDiscoverApi:
    """Unit tests for discover_api(spec_dict) -> list of endpoint dicts."""

    def test_extracts_all_endpoints(self) -> None:
        endpoints = discover_api(SIMPLE_SPEC)
        assert len(endpoints) == 5

    def test_endpoint_structure(self) -> None:
        endpoints = discover_api(SIMPLE_SPEC)
        first = endpoints[0]
        assert "method" in first
        assert "path" in first
        assert "risk" in first
        assert "summary" in first

    def test_methods_uppercased(self) -> None:
        endpoints = discover_api(SIMPLE_SPEC)
        for ep in endpoints:
            assert ep["method"] == ep["method"].upper()

    def test_risk_classification_applied(self) -> None:
        endpoints = discover_api(SIMPLE_SPEC)
        by_key = {(ep["method"], ep["path"]): ep for ep in endpoints}
        assert by_key[("GET", "/users")]["risk"] == "low"
        assert by_key[("PUT", "/users/{id}")]["risk"] == "medium"
        assert by_key[("DELETE", "/users/{id}")]["risk"] == "high"

    def test_empty_paths(self) -> None:
        endpoints = discover_api(EMPTY_SPEC)
        assert endpoints == []

    def test_no_paths_key(self) -> None:
        endpoints = discover_api(NO_PATHS_SPEC)
        assert endpoints == []

    def test_mixed_methods_spec(self) -> None:
        endpoints = discover_api(MIXED_METHODS_SPEC)
        assert len(endpoints) == 5
        risks = {ep["risk"] for ep in endpoints}
        assert "low" in risks
        assert "medium" in risks
        assert "high" in risks

    def test_summary_extracted(self) -> None:
        endpoints = discover_api(SIMPLE_SPEC)
        by_key = {(ep["method"], ep["path"]): ep for ep in endpoints}
        assert by_key[("GET", "/users")]["summary"] == "List users"
        assert by_key[("DELETE", "/users/{id}")]["summary"] == "Delete user"

    def test_missing_summary_defaults_to_empty(self) -> None:
        spec: dict[str, Any] = {
            "paths": {
                "/test": {
                    "get": {},
                },
            },
        }
        endpoints = discover_api(spec)
        assert endpoints[0]["summary"] == ""


# ── WardenAtArmsStrategy.reason() tests ──────────────────────────────


class TestWardenAtArmsStrategyReason:
    """Integration tests for the strategy's reason() method."""

    async def test_reason_with_spec_returns_classified_endpoints(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("API discovery complete.")
        strategy = WardenAtArmsStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Discover the API"}],
            model="fake-model",
            llm=llm,
            spec=SIMPLE_SPEC,
        )

        assert isinstance(result, ReasoningResult)
        assert result.done is True
        assert result.response is not None
        # Response should mention discovered endpoints
        assert "GET" in result.response
        assert "/users" in result.response

    async def test_reason_without_spec_falls_back_to_llm(self) -> None:
        """When no spec is provided, delegates to ReactStrategy-style LLM call."""
        llm = FakeLLMClient()
        llm.set_simple_response("I can help you discover APIs.")
        strategy = WardenAtArmsStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Help me find an API"}],
            model="fake-model",
            llm=llm,
        )

        assert isinstance(result, ReasoningResult)
        assert result.done is True
        assert result.response == "I can help you discover APIs."
        assert len(llm.calls) == 1

    async def test_reason_includes_risk_summary(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Summary complete.")
        strategy = WardenAtArmsStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Analyze this API"}],
            model="fake-model",
            llm=llm,
            spec=SIMPLE_SPEC,
        )

        assert result.response is not None
        assert "low" in result.response.lower()
        assert "high" in result.response.lower()

    async def test_reason_empty_spec_falls_back(self) -> None:
        """Empty spec (no paths) should fall back to LLM."""
        llm = FakeLLMClient()
        llm.set_simple_response("No endpoints found in spec.")
        strategy = WardenAtArmsStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Discover API"}],
            model="fake-model",
            llm=llm,
            spec=EMPTY_SPEC,
        )

        assert result.done is True
        # With an empty spec, should fall back to LLM
        assert len(llm.calls) == 1

    async def test_reason_tracks_tokens(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Done.")
        strategy = WardenAtArmsStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Discover"}],
            model="fake-model",
            llm=llm,
        )

        assert result.input_tokens >= 0
        assert result.output_tokens >= 0

    async def test_reason_returns_reasoning_trace(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Analysis done.")
        strategy = WardenAtArmsStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Analyze API"}],
            model="fake-model",
            llm=llm,
            spec=SIMPLE_SPEC,
        )

        assert result.reasoning_trace != ""


# ── WardenAtArmsStrategy construction tests ──────────────────────────


class TestWardenAtArmsStrategyConstruction:
    """Construction and configuration tests."""

    def test_default_max_rounds(self) -> None:
        strategy = WardenAtArmsStrategy()
        assert strategy.max_rounds == 5

    def test_custom_max_rounds(self) -> None:
        strategy = WardenAtArmsStrategy(max_rounds=10)
        assert strategy.max_rounds == 10
