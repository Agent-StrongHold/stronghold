"""Tool fingerprint canonicalization tests."""

from __future__ import annotations

from stronghold.security import tool_fingerprint as fp


def test_same_input_produces_same_fingerprint() -> None:
    a = fp.compute(
        {
            "name": "github_search",
            "description": "Search GitHub",
            "input_schema": {"type": "object"},
        }
    )
    b = fp.compute(
        {
            "name": "github_search",
            "description": "Search GitHub",
            "input_schema": {"type": "object"},
        }
    )
    assert a.value == b.value
    assert a.schema_hash == b.schema_hash


def test_key_order_does_not_change_fingerprint() -> None:
    a = fp.compute(
        {
            "name": "x",
            "description": "y",
            "input_schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "int"}},
            },
        }
    )
    b = fp.compute(
        {
            "input_schema": {
                "properties": {"b": {"type": "int"}, "a": {"type": "string"}},
                "type": "object",
            },
            "description": "y",
            "name": "x",
        }
    )
    assert a.value == b.value


def test_description_change_changes_fingerprint() -> None:
    a = fp.compute({"name": "x", "description": "old", "input_schema": {"type": "object"}})
    b = fp.compute({"name": "x", "description": "new", "input_schema": {"type": "object"}})
    assert a.value != b.value


def test_schema_change_changes_both_value_and_schema_hash() -> None:
    a = fp.compute({"name": "x", "description": "y", "input_schema": {"type": "object"}})
    b = fp.compute(
        {"name": "x", "description": "y", "input_schema": {"type": "object", "required": ["q"]}}
    )
    assert a.value != b.value
    assert a.schema_hash != b.schema_hash


def test_name_change_keeps_schema_hash_stable() -> None:
    a = fp.compute({"name": "x", "description": "y", "input_schema": {"type": "object"}})
    b = fp.compute({"name": "y", "description": "y", "input_schema": {"type": "object"}})
    assert a.value != b.value
    assert a.schema_hash == b.schema_hash


def test_openai_function_format_matches_flat_format() -> None:
    flat = fp.compute(
        {
            "name": "github_search",
            "description": "Search",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    )
    openai = fp.compute(
        {
            "type": "function",
            "function": {
                "name": "github_search",
                "description": "Search",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
            },
        }
    )
    assert flat.value == openai.value


def test_unicode_normalization_in_description() -> None:
    a = fp.compute({"name": "x", "description": "café", "input_schema": {}})
    b = fp.compute({"name": "x", "description": "café", "input_schema": {}})
    assert a.value == b.value
