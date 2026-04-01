"""Tests for tool schema pruner — context budget optimization."""

from __future__ import annotations

import json
from typing import Any

from stronghold.tools.schema_pruner import (
    estimate_schema_tokens,
    prune_schema,
    simplify_for_tier,
)


def _make_schema() -> dict[str, Any]:
    """Build a realistic OpenAI-style JSON Schema for testing."""
    return {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The Home Assistant entity ID to control",
            },
            "service": {
                "type": "string",
                "description": "The HA service to call (e.g. turn_on, turn_off)",
            },
            "brightness": {
                "type": "integer",
                "description": "Optional brightness level (0-255) for light entities",
            },
            "color_temp": {
                "type": "integer",
                "description": "Optional colour temperature in mireds",
            },
        },
        "required": ["entity_id", "service"],
    }


class TestPruneSchema:
    def test_removes_single_unused_param(self) -> None:
        schema = _make_schema()
        result = prune_schema(schema, ["color_temp"])
        assert "color_temp" not in result["properties"]
        assert "entity_id" in result["properties"]
        assert "service" in result["properties"]
        assert "brightness" in result["properties"]

    def test_removes_multiple_unused_params(self) -> None:
        schema = _make_schema()
        result = prune_schema(schema, ["brightness", "color_temp"])
        assert "brightness" not in result["properties"]
        assert "color_temp" not in result["properties"]
        assert len(result["properties"]) == 2

    def test_ignores_nonexistent_params(self) -> None:
        schema = _make_schema()
        result = prune_schema(schema, ["nonexistent_field"])
        assert len(result["properties"]) == 4

    def test_does_not_mutate_original(self) -> None:
        schema = _make_schema()
        prune_schema(schema, ["brightness"])
        assert "brightness" in schema["properties"]

    def test_removes_param_from_required(self) -> None:
        schema = _make_schema()
        schema["required"] = ["entity_id", "service", "brightness"]
        result = prune_schema(schema, ["brightness"])
        assert "brightness" not in result.get("required", [])
        assert "entity_id" in result["required"]

    def test_empty_unused_list_returns_copy(self) -> None:
        schema = _make_schema()
        result = prune_schema(schema, [])
        assert result == schema
        assert result is not schema


class TestSimplifyForTier:
    def test_frontier_returns_full_schema(self) -> None:
        schema = _make_schema()
        result = simplify_for_tier(schema, "frontier")
        assert result == schema

    def test_small_removes_optional_params(self) -> None:
        schema = _make_schema()
        result = simplify_for_tier(schema, "small")
        assert "entity_id" in result["properties"]
        assert "service" in result["properties"]
        assert "brightness" not in result["properties"]
        assert "color_temp" not in result["properties"]

    def test_small_truncates_descriptions(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A" * 200,
                },
            },
            "required": ["query"],
        }
        result = simplify_for_tier(schema, "small")
        props = result["properties"]
        desc = props["query"]["description"]
        assert len(desc) <= 80

    def test_small_does_not_mutate_original(self) -> None:
        schema = _make_schema()
        simplify_for_tier(schema, "small")
        assert "brightness" in schema["properties"]

    def test_small_preserves_required_list(self) -> None:
        schema = _make_schema()
        result = simplify_for_tier(schema, "small")
        assert result["required"] == ["entity_id", "service"]

    def test_small_handles_no_required_field(self) -> None:
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
        }
        result = simplify_for_tier(schema, "small")
        assert "query" not in result.get("properties", {})


class TestEstimateSchemaTokens:
    def test_empty_schema(self) -> None:
        result = estimate_schema_tokens({})
        assert result == 0

    def test_small_schema(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        result = estimate_schema_tokens(schema)
        assert result > 0

    def test_larger_schema_has_more_tokens(self) -> None:
        small: dict[str, Any] = {"type": "object", "properties": {}}
        large = _make_schema()
        assert estimate_schema_tokens(large) > estimate_schema_tokens(small)

    def test_rough_chars_over_four(self) -> None:
        schema = _make_schema()
        json_str = json.dumps(schema)
        expected = len(json_str) // 4
        result = estimate_schema_tokens(schema)
        assert result == expected
