"""Canonical ToolFingerprint computation.

A fingerprint is the sha256 hex of canonical JSON over (name, description,
input_schema). Whitespace and key order are normalised so logically-equal
declarations produce equal fingerprints. ``schema_hash`` is the hash of
``input_schema`` alone — used for rug-pull diagnostics where the *name*
matches a known tool but the *schema* has drifted.

Two acceptable input shapes are supported:

- A ``dict`` matching the OpenAI/LiteLLM tool declaration format:
  ``{"type": "function", "function": {"name": ..., "description": ...,
  "parameters": {...}}}``
- A flat dict: ``{"name": ..., "description": ..., "input_schema": {...}}``
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from stronghold.types.security import ToolFingerprint


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _extract(declaration: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if "function" in declaration and isinstance(declaration["function"], dict):
        fn = declaration["function"]
        return (
            str(fn.get("name", "")),
            str(fn.get("description", "")),
            dict(fn.get("parameters") or {}),
        )
    return (
        str(declaration.get("name", "")),
        str(declaration.get("description", "")),
        dict(declaration.get("input_schema") or declaration.get("parameters") or {}),
    )


def schema_hash(input_schema: dict[str, Any]) -> str:
    """Hash of input_schema alone — stable under name/description changes."""
    return hashlib.sha256(_canonical(input_schema).encode("utf-8")).hexdigest()


def compute(declaration: dict[str, Any]) -> ToolFingerprint:
    """Compute a canonical ToolFingerprint from a declaration dict."""
    name, description, schema = _extract(declaration)
    payload = {"name": name, "description": description, "input_schema": schema}
    fingerprint_value = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return ToolFingerprint(
        value=fingerprint_value,
        name=name,
        schema_hash=schema_hash(schema),
    )
