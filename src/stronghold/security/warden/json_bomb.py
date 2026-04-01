"""Warden: JSON bomb detection.

Detects JSON payloads designed to consume excessive memory or processing time
through deep nesting, excessive keys, or oversized string values. These
"JSON bombs" can bypass earlier Warden layers because they contain no
injection patterns — they attack the parser/runtime, not the LLM.

Addresses SEC issue #34.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def detect_json_bomb(
    text: str,
    *,
    max_depth: int = 20,
    max_keys: int = 1000,
    max_string_length: int = 100_000,
) -> bool:
    """Detect whether a JSON string is a JSON bomb.

    A JSON bomb is a payload designed to cause excessive resource consumption
    via deep nesting, excessive keys, or oversized string values.

    Args:
        text: The raw JSON string to check.
        max_depth: Maximum allowed nesting depth. Depths exceeding this are bombs.
        max_keys: Maximum total number of keys across all objects. Exceeding = bomb.
        max_string_length: Maximum allowed length for any single string value.

    Returns:
        True if the payload is a JSON bomb, False otherwise.
        Invalid JSON returns False (not a bomb, just bad input).
    """
    if not text:
        return False

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False

    return _walk(
        parsed,
        max_depth=max_depth,
        max_keys=max_keys,
        max_string_length=max_string_length,
    )


def estimate_expansion_ratio(text: str) -> float:
    """Estimate the expansion ratio of a JSON payload.

    Returns the ratio of the parsed structure's in-memory size to the raw text
    length. A high ratio may indicate a JSON bomb (small text that expands into
    a large structure).

    Args:
        text: The raw JSON string to analyze.

    Returns:
        Ratio as a float. Returns 0.0 for invalid JSON or empty input.
    """
    if not text:
        return 0.0

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return 0.0

    structure_size = sys.getsizeof(parsed) + _deep_getsizeof(parsed)
    text_size = len(text)

    if text_size == 0:
        return 0.0

    return structure_size / text_size


def _walk(
    obj: Any,  # noqa: ANN401
    *,
    max_depth: int,
    max_keys: int,
    max_string_length: int,
    _current_depth: int = 0,
    _key_count: list[int] | None = None,
) -> bool:
    """Recursively walk a parsed JSON structure checking bomb indicators.

    Returns True (bomb detected) as soon as any threshold is exceeded.
    """
    if _key_count is None:
        _key_count = [0]

    # Check depth
    if _current_depth > max_depth:
        return True

    if isinstance(obj, dict):
        _key_count[0] += len(obj)
        if _key_count[0] > max_keys:
            return True

        for value in obj.values():
            if _walk(
                value,
                max_depth=max_depth,
                max_keys=max_keys,
                max_string_length=max_string_length,
                _current_depth=_current_depth + 1,
                _key_count=_key_count,
            ):
                return True

    elif isinstance(obj, list):
        for item in obj:
            if _walk(
                item,
                max_depth=max_depth,
                max_keys=max_keys,
                max_string_length=max_string_length,
                _current_depth=_current_depth + 1,
                _key_count=_key_count,
            ):
                return True

    elif isinstance(obj, str):
        if len(obj) > max_string_length:
            return True

    return False


def _deep_getsizeof(obj: Any) -> int:  # noqa: ANN401
    """Recursively estimate in-memory size of a parsed JSON structure."""
    total = 0

    if isinstance(obj, dict):
        for key, value in obj.items():
            total += sys.getsizeof(key)
            total += sys.getsizeof(value) + _deep_getsizeof(value)
    elif isinstance(obj, list):
        for item in obj:
            total += sys.getsizeof(item) + _deep_getsizeof(item)

    return total
