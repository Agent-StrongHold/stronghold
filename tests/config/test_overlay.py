"""Tests for LiteLLM config overlay: fetch, parse, merge."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
import respx

from stronghold.config.overlay import (
    ModelOverlay,
    fetch_litellm_models,
    merge_models,
    parse_overlay_config,
)


class TestParseOverlayConfig:
    """parse_overlay_config: YAML dict -> dict[str, ModelOverlay]."""

    def test_parses_all_fields(self) -> None:
        """All four overlay fields are parsed correctly."""
        raw: dict[str, Any] = {
            "mistral-large": {
                "quality": 0.68,
                "tier": "frontier",
                "strengths": ["code", "reasoning"],
                "speed": 60.0,
            },
        }
        result = parse_overlay_config(raw)
        assert "mistral-large" in result
        overlay = result["mistral-large"]
        assert overlay.quality == 0.68
        assert overlay.tier == "frontier"
        assert overlay.strengths == ["code", "reasoning"]
        assert overlay.speed == 60.0

    def test_missing_fields_get_defaults(self) -> None:
        """Fields not specified in the overlay get default values."""
        raw: dict[str, Any] = {
            "my-model": {"quality": 0.9},
        }
        result = parse_overlay_config(raw)
        overlay = result["my-model"]
        assert overlay.quality == 0.9
        assert overlay.tier == "medium"
        assert overlay.strengths == []
        assert overlay.speed == 100.0

    def test_multiple_models(self) -> None:
        """Multiple model entries are all parsed."""
        raw: dict[str, Any] = {
            "model-a": {"quality": 0.3, "tier": "small"},
            "model-b": {"quality": 0.8, "tier": "large"},
        }
        result = parse_overlay_config(raw)
        assert len(result) == 2
        assert result["model-a"].quality == 0.3
        assert result["model-b"].quality == 0.8

    def test_empty_dict_returns_empty(self) -> None:
        """Empty input returns empty dict."""
        assert parse_overlay_config({}) == {}


class TestFetchLiteLLMModels:
    """fetch_litellm_models: HTTP call to LiteLLM /model/info."""

    @respx.mock
    async def test_returns_model_list(self) -> None:
        """Successful response returns the model data list."""
        model_data = [
            {
                "model_name": "mistral-large",
                "model_info": {"id": "mistral/mistral-large-latest"},
            },
            {
                "model_name": "gemini-flash",
                "model_info": {"id": "gemini/gemini-2.5-flash"},
            },
        ]
        respx.get("http://litellm:4000/model/info").mock(
            return_value=httpx.Response(200, json={"data": model_data})
        )

        result = await fetch_litellm_models("http://litellm:4000", "sk-test-key")
        assert len(result) == 2
        assert result[0]["model_name"] == "mistral-large"
        assert result[1]["model_name"] == "gemini-flash"

    @respx.mock
    async def test_returns_empty_on_http_error(self) -> None:
        """HTTP error returns empty list (graceful degradation)."""
        respx.get("http://litellm:4000/model/info").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        result = await fetch_litellm_models("http://litellm:4000", "sk-test-key")
        assert result == []

    @respx.mock
    async def test_returns_empty_on_connection_error(self) -> None:
        """Connection error returns empty list (graceful degradation)."""
        respx.get("http://litellm:4000/model/info").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await fetch_litellm_models("http://litellm:4000", "sk-test-key")
        assert result == []

    @respx.mock
    async def test_sends_auth_header(self) -> None:
        """Request includes Authorization: Bearer header."""
        route = respx.get("http://litellm:4000/model/info").mock(
            return_value=httpx.Response(200, json={"data": []})
        )

        await fetch_litellm_models("http://litellm:4000", "sk-my-key")
        assert route.called
        request = route.calls[0].request
        assert request.headers["Authorization"] == "Bearer sk-my-key"

    @respx.mock
    async def test_returns_empty_on_missing_data_key(self) -> None:
        """Response without 'data' key returns empty list."""
        respx.get("http://litellm:4000/model/info").mock(
            return_value=httpx.Response(200, json={"models": []})
        )

        result = await fetch_litellm_models("http://litellm:4000", "sk-test-key")
        assert result == []


class TestMergeModels:
    """merge_models: combine LiteLLM models + Stronghold overlays."""

    def test_litellm_model_gets_overlay_metadata(self) -> None:
        """LiteLLM model with matching overlay gets overlay values."""
        litellm_models: list[dict[str, Any]] = [
            {
                "model_name": "mistral-large",
                "model_info": {"id": "mistral/mistral-large-latest"},
                "litellm_params": {"model": "mistral/mistral-large-latest"},
            },
        ]
        overlays = {
            "mistral-large": ModelOverlay(
                quality=0.85,
                tier="frontier",
                strengths=["code", "reasoning"],
                speed=60.0,
            ),
        }
        existing: dict[str, Any] = {}

        result = merge_models(litellm_models, overlays, existing)
        assert "mistral-large" in result
        model = result["mistral-large"]
        assert model["quality"] == 0.85
        assert model["tier"] == "frontier"
        assert model["strengths"] == ["code", "reasoning"]
        assert model["speed"] == 60.0
        assert model["litellm_id"] == "mistral/mistral-large-latest"

    def test_litellm_model_without_overlay_gets_defaults(self) -> None:
        """LiteLLM model without overlay gets default quality/tier/speed."""
        litellm_models: list[dict[str, Any]] = [
            {
                "model_name": "new-model",
                "model_info": {"id": "provider/new-model"},
                "litellm_params": {"model": "provider/new-model"},
            },
        ]
        overlays: dict[str, ModelOverlay] = {}
        existing: dict[str, Any] = {}

        result = merge_models(litellm_models, overlays, existing)
        assert "new-model" in result
        model = result["new-model"]
        assert model["quality"] == 0.5
        assert model["tier"] == "medium"
        assert model["strengths"] == []
        assert model["speed"] == 100.0

    def test_stale_overlay_produces_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Overlay entry not in LiteLLM produces a warning log."""
        litellm_models: list[dict[str, Any]] = []
        overlays = {
            "stale-model": ModelOverlay(quality=0.9, tier="large"),
        }
        existing: dict[str, Any] = {}

        with caplog.at_level(logging.WARNING, logger="stronghold.config.overlay"):
            merge_models(litellm_models, overlays, existing)

        assert any("stale-model" in msg for msg in caplog.messages)

    def test_existing_config_models_preserved(self) -> None:
        """Models in existing config but not in LiteLLM are preserved."""
        litellm_models: list[dict[str, Any]] = [
            {
                "model_name": "litellm-model",
                "model_info": {"id": "provider/litellm-model"},
                "litellm_params": {"model": "provider/litellm-model"},
            },
        ]
        overlays: dict[str, ModelOverlay] = {}
        existing: dict[str, Any] = {
            "manual-model": {
                "provider": "custom",
                "tier": "small",
                "quality": 0.3,
                "speed": 500,
                "litellm_id": "custom/manual",
                "strengths": ["chat"],
            },
        }

        result = merge_models(litellm_models, overlays, existing)
        assert "manual-model" in result
        assert result["manual-model"]["provider"] == "custom"
        assert "litellm-model" in result

    def test_empty_litellm_falls_back_to_existing(self) -> None:
        """Empty LiteLLM response preserves all existing config models."""
        litellm_models: list[dict[str, Any]] = []
        overlays: dict[str, ModelOverlay] = {}
        existing: dict[str, Any] = {
            "existing-a": {
                "provider": "p",
                "tier": "small",
                "quality": 0.4,
                "speed": 200,
                "litellm_id": "p/a",
                "strengths": ["chat"],
            },
            "existing-b": {
                "provider": "p",
                "tier": "large",
                "quality": 0.9,
                "speed": 100,
                "litellm_id": "p/b",
                "strengths": ["code"],
            },
        }

        result = merge_models(litellm_models, overlays, existing)
        assert "existing-a" in result
        assert "existing-b" in result
        assert len(result) == 2

    def test_litellm_model_overrides_existing_config(self) -> None:
        """When a model exists in both LiteLLM and existing config, LiteLLM wins."""
        litellm_models: list[dict[str, Any]] = [
            {
                "model_name": "shared-model",
                "model_info": {"id": "new-provider/shared"},
                "litellm_params": {"model": "new-provider/shared"},
            },
        ]
        overlays = {
            "shared-model": ModelOverlay(quality=0.9, tier="frontier"),
        }
        existing: dict[str, Any] = {
            "shared-model": {
                "provider": "old-provider",
                "tier": "small",
                "quality": 0.3,
                "speed": 500,
                "litellm_id": "old/shared",
                "strengths": ["chat"],
            },
        }

        result = merge_models(litellm_models, overlays, existing)
        model = result["shared-model"]
        # LiteLLM + overlay values take precedence
        assert model["litellm_id"] == "new-provider/shared"
        assert model["quality"] == 0.9
        assert model["tier"] == "frontier"

    def test_provider_extracted_from_litellm_id(self) -> None:
        """Provider name is extracted from the litellm_id prefix."""
        litellm_models: list[dict[str, Any]] = [
            {
                "model_name": "some-model",
                "model_info": {"id": "openai/gpt-4"},
                "litellm_params": {"model": "openai/gpt-4"},
            },
        ]
        overlays: dict[str, ModelOverlay] = {}
        existing: dict[str, Any] = {}

        result = merge_models(litellm_models, overlays, existing)
        assert result["some-model"]["provider"] == "openai"
