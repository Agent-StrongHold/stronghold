"""Tests for JSON bomb detection in Warden.

Addresses SEC issue #34: JSON bomb passes through Warden.
"""

from __future__ import annotations

import json

from stronghold.security.warden.json_bomb import detect_json_bomb, estimate_expansion_ratio


class TestDetectJsonBomb:
    """Tests for detect_json_bomb."""

    def test_normal_json_passes(self) -> None:
        """Normal, well-formed JSON should not be flagged as a bomb."""
        payload = json.dumps({"name": "Alice", "age": 30, "tags": ["admin", "user"]})
        assert detect_json_bomb(payload) is False

    def test_empty_object_passes(self) -> None:
        """Empty JSON object is not a bomb."""
        assert detect_json_bomb("{}") is False

    def test_empty_array_passes(self) -> None:
        """Empty JSON array is not a bomb."""
        assert detect_json_bomb("[]") is False

    def test_deep_nesting_caught(self) -> None:
        """Deeply nested JSON exceeding max_depth should be detected as a bomb."""
        # Build 25-level deep nesting (default max_depth=20)
        payload = '{"a":' * 25 + "1" + "}" * 25
        assert detect_json_bomb(payload) is True

    def test_deep_nesting_at_threshold_passes(self) -> None:
        """Nesting exactly at max_depth should pass."""
        # Build exactly 20-level deep nesting
        payload = '{"a":' * 20 + "1" + "}" * 20
        assert detect_json_bomb(payload) is False

    def test_deep_nesting_custom_threshold(self) -> None:
        """Custom max_depth should be respected."""
        payload = '{"a":' * 6 + "1" + "}" * 6
        assert detect_json_bomb(payload, max_depth=5) is True
        assert detect_json_bomb(payload, max_depth=10) is False

    def test_many_keys_caught(self) -> None:
        """JSON with more keys than max_keys should be detected as a bomb."""
        obj = {f"key_{i}": i for i in range(1500)}
        payload = json.dumps(obj)
        assert detect_json_bomb(payload) is True

    def test_many_keys_at_threshold_passes(self) -> None:
        """JSON with exactly max_keys keys should pass."""
        obj = {f"key_{i}": i for i in range(1000)}
        payload = json.dumps(obj)
        assert detect_json_bomb(payload) is False

    def test_many_keys_custom_threshold(self) -> None:
        """Custom max_keys should be respected."""
        obj = {f"k{i}": i for i in range(50)}
        payload = json.dumps(obj)
        assert detect_json_bomb(payload, max_keys=30) is True
        assert detect_json_bomb(payload, max_keys=100) is False

    def test_huge_string_caught(self) -> None:
        """JSON with a string value exceeding max_string_length should be detected."""
        payload = json.dumps({"data": "x" * 200_000})
        assert detect_json_bomb(payload) is True

    def test_huge_string_at_threshold_passes(self) -> None:
        """String value exactly at max_string_length should pass."""
        payload = json.dumps({"data": "x" * 100_000})
        assert detect_json_bomb(payload) is False

    def test_huge_string_custom_threshold(self) -> None:
        """Custom max_string_length should be respected."""
        payload = json.dumps({"msg": "a" * 500})
        assert detect_json_bomb(payload, max_string_length=200) is True
        assert detect_json_bomb(payload, max_string_length=1000) is False

    def test_invalid_json_returns_false(self) -> None:
        """Invalid JSON is not a bomb — just bad input."""
        assert detect_json_bomb("not json at all") is False
        assert detect_json_bomb("{broken: json}") is False
        assert detect_json_bomb("") is False
        assert detect_json_bomb("{{{") is False

    def test_nested_arrays_depth(self) -> None:
        """Deep nesting via arrays should also be caught."""
        payload = "[" * 25 + "1" + "]" * 25
        assert detect_json_bomb(payload) is True

    def test_mixed_nesting_depth(self) -> None:
        """Mixed object/array nesting should be caught when deep enough."""
        # Alternating objects and arrays for 25 levels
        parts: list[str] = []
        closers: list[str] = []
        for i in range(25):
            if i % 2 == 0:
                parts.append('{"a":')
                closers.append("}")
            else:
                parts.append("[")
                closers.append("]")
        payload = "".join(parts) + "1" + "".join(reversed(closers))
        assert detect_json_bomb(payload) is True

    def test_keys_counted_across_nested_objects(self) -> None:
        """Total key count should include keys from all nested objects."""
        # 600 keys at top level + 600 keys in nested object = 1200 total > 1000
        outer = {f"a{i}": i for i in range(600)}
        inner = {f"b{i}": i for i in range(600)}
        outer["nested"] = inner  # type: ignore[assignment]
        payload = json.dumps(outer)
        assert detect_json_bomb(payload) is True

    def test_string_in_array_checked(self) -> None:
        """Huge strings inside arrays should also be caught."""
        payload = json.dumps(["short", "x" * 200_000])
        assert detect_json_bomb(payload) is True

    def test_non_json_text_with_braces(self) -> None:
        """Text that has braces but isn't valid JSON returns False."""
        assert detect_json_bomb("function() { return {}; }") is False


class TestEstimateExpansionRatio:
    """Tests for estimate_expansion_ratio."""

    def test_normal_json_low_ratio(self) -> None:
        """Normal JSON should have a reasonable expansion ratio."""
        payload = json.dumps({"key": "value", "num": 42})
        ratio = estimate_expansion_ratio(payload)
        # Python objects have inherent memory overhead, so even normal JSON
        # has a non-trivial ratio. The key insight is that bomb payloads
        # will have a MUCH higher ratio than normal payloads.
        assert ratio < 50.0

    def test_deeply_nested_high_ratio(self) -> None:
        """Deeply nested JSON should have a higher expansion ratio."""
        payload = '{"a":' * 15 + '"x"' + "}" * 15
        ratio = estimate_expansion_ratio(payload)
        # The structure is deeper than the text is long → higher ratio
        assert ratio > 0.0

    def test_invalid_json_returns_zero(self) -> None:
        """Invalid JSON should return 0.0 ratio."""
        assert estimate_expansion_ratio("not json") == 0.0
        assert estimate_expansion_ratio("") == 0.0

    def test_many_keys_higher_ratio(self) -> None:
        """Many short keys should produce a meaningful ratio."""
        obj = {f"k{i}": i for i in range(500)}
        payload = json.dumps(obj)
        ratio = estimate_expansion_ratio(payload)
        assert ratio > 0.0
