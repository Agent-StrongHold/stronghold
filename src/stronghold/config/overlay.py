"""Model config overlay: fetch from LiteLLM + merge Stronghold metadata.

Instead of duplicating LiteLLM's model list, Stronghold maintains a thin overlay
with only Stronghold-specific metadata (quality, tier, strengths, speed).
At startup, fetch LiteLLM's model list and merge the overlay on top.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("stronghold.config.overlay")


@dataclass
class ModelOverlay:
    """Stronghold-specific metadata for a model (not in LiteLLM)."""

    quality: float = 0.5
    tier: str = "medium"
    strengths: list[str] = field(default_factory=list)
    speed: float = 100.0


def parse_overlay_config(raw: dict[str, Any]) -> dict[str, ModelOverlay]:
    """Parse model_overrides section from config into ModelOverlay objects.

    Each key is a model name, value is a dict with optional fields:
    quality, tier, strengths, speed.  Missing fields get dataclass defaults.
    """
    result: dict[str, ModelOverlay] = {}
    for model_name, values in raw.items():
        if not isinstance(values, dict):
            logger.warning("Skipping non-dict overlay entry: %s", model_name)
            continue
        result[model_name] = ModelOverlay(
            quality=values.get("quality", 0.5),
            tier=values.get("tier", "medium"),
            strengths=values.get("strengths", []),
            speed=values.get("speed", 100.0),
        )
    return result


async def fetch_litellm_models(litellm_url: str, api_key: str) -> list[dict[str, Any]]:
    """Fetch model list from LiteLLM's /model/info endpoint.

    Returns list of model info dicts.  Returns empty list on failure
    (graceful degradation — the system falls back to existing config).
    """
    url = f"{litellm_url.rstrip('/')}/model/info"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:  # noqa: PLR2004
            logger.warning(
                "LiteLLM /model/info returned %d — falling back to existing config",
                resp.status_code,
            )
            return []

        data = resp.json()
        models: list[dict[str, Any]] = data.get("data", [])
        if not isinstance(models, list):
            logger.warning("LiteLLM /model/info 'data' is not a list — ignoring")
            return []
        return models

    except httpx.ConnectError:
        logger.warning("Cannot connect to LiteLLM at %s — falling back to existing config", url)
        return []
    except Exception:
        logger.exception("Unexpected error fetching LiteLLM models")
        return []


def _extract_litellm_id(model_info: dict[str, Any]) -> str:
    """Extract the litellm_id from a LiteLLM model info dict.

    Tries litellm_params.model first, then model_info.id.
    """
    litellm_params = model_info.get("litellm_params", {})
    if isinstance(litellm_params, dict) and "model" in litellm_params:
        return str(litellm_params["model"])
    info = model_info.get("model_info", {})
    if isinstance(info, dict) and "id" in info:
        return str(info["id"])
    return ""


def _extract_provider(litellm_id: str) -> str:
    """Extract provider name from a litellm_id like 'openai/gpt-4'."""
    if "/" in litellm_id:
        return litellm_id.split("/", 1)[0]
    return "unknown"


def merge_models(
    litellm_models: list[dict[str, Any]],
    overlays: dict[str, ModelOverlay],
    existing_config: dict[str, Any],
) -> dict[str, Any]:
    """Merge LiteLLM model list with Stronghold overlays.

    Priority order:
    1. Models from LiteLLM get overlay metadata if available, defaults otherwise.
    2. Models in overlay but not in LiteLLM produce a warning (stale overlay).
    3. Models in existing config but not in LiteLLM are preserved (manual additions).

    Returns merged models dict compatible with StrongholdConfig.models.
    """
    result: dict[str, Any] = {}
    litellm_names: set[str] = set()

    # Phase 1: Process LiteLLM models
    for model_info in litellm_models:
        name = model_info.get("model_name", "")
        if not name:
            continue
        litellm_names.add(name)

        litellm_id = _extract_litellm_id(model_info)
        provider = _extract_provider(litellm_id)

        overlay = overlays.get(name, ModelOverlay())
        result[name] = {
            "provider": provider,
            "litellm_id": litellm_id,
            "tier": overlay.tier,
            "quality": overlay.quality,
            "speed": overlay.speed,
            "strengths": overlay.strengths,
            "modality": "text",
        }

    # Phase 2: Warn about stale overlays
    for overlay_name in overlays:
        if overlay_name not in litellm_names:
            logger.warning(
                "Model overlay '%s' has no matching LiteLLM model — stale entry?",
                overlay_name,
            )

    # Phase 3: Preserve existing config models not in LiteLLM
    for name, model_data in existing_config.items():
        if name not in result:
            result[name] = model_data

    return result
