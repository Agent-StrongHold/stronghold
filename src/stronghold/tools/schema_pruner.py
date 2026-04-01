"""Tool schema pruner — shrink JSON Schema tool definitions for context budget.

Three operations:
- prune_schema: remove specific unused parameters
- simplify_for_tier: strip optional params + truncate descriptions for small models
- estimate_schema_tokens: rough token count (chars / 4)
"""

from __future__ import annotations

import copy
import json
from typing import Any

_MAX_DESCRIPTION_LEN_SMALL = 80


def prune_schema(schema: dict[str, Any], unused_params: list[str]) -> dict[str, Any]:
    """Remove *unused_params* from a JSON Schema tool definition.

    Returns a deep copy — the original schema is never mutated.
    """
    result: dict[str, Any] = copy.deepcopy(schema)
    properties: dict[str, Any] = result.get("properties", {})
    for param in unused_params:
        properties.pop(param, None)
    required: list[str] | None = result.get("required")
    if required is not None:
        result["required"] = [r for r in required if r not in unused_params]
    return result


def simplify_for_tier(schema: dict[str, Any], tier: str) -> dict[str, Any]:
    """Simplify a schema for a given model tier.

    * ``"frontier"`` — return the full schema (deep copy).
    * ``"small"`` — keep only required params; truncate descriptions to
      *_MAX_DESCRIPTION_LEN_SMALL* characters.
    """
    result: dict[str, Any] = copy.deepcopy(schema)
    if tier == "frontier":
        return result

    # --- small tier ---
    required_set: set[str] = set(result.get("required", []))
    properties: dict[str, Any] = result.get("properties", {})

    # Drop optional (non-required) properties
    optional_keys = [k for k in properties if k not in required_set]
    for key in optional_keys:
        del properties[key]

    # Truncate remaining descriptions
    for prop in properties.values():
        desc: str | None = prop.get("description")
        if desc is not None and len(desc) > _MAX_DESCRIPTION_LEN_SMALL:
            prop["description"] = desc[:_MAX_DESCRIPTION_LEN_SMALL]

    return result


def estimate_schema_tokens(schema: dict[str, Any]) -> int:
    """Rough token estimate for a JSON Schema dict.

    Uses the simple heuristic: ``len(json.dumps(schema)) // 4``.
    Returns 0 for an empty schema.
    """
    if not schema:
        return 0
    return len(json.dumps(schema)) // 4
