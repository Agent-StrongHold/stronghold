"""Debug endpoints — routing dry-run and diagnostics."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.router.explainer import explain_candidates, explain_selection
from stronghold.types.model import ModelConfig, ProviderConfig

logger = logging.getLogger("stronghold.api.debug")

router = APIRouter()


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


@router.post("/v1/stronghold/debug/route-explain")
async def route_explain(request: Request) -> JSONResponse:
    """Dry-run classification + routing. Returns what WOULD happen.

    Does NOT dispatch to an agent — purely diagnostic.

    Body:
        messages: list of {role, content} dicts
        intent_hint: optional string to override classification

    Response:
        intent: classification result
        candidates: scored candidate breakdown
        decision: selected model id
        explanation: human-readable summary
    """
    await _require_admin(request)

    container = request.app.state.container
    body = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    intent_hint: str = body.get("intent_hint", "")

    # ── 1. Classify intent ──
    if intent_hint and intent_hint in container.config.task_types:
        from stronghold.types.intent import Intent

        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content", ""))
                break
        intent = Intent(
            task_type=intent_hint,
            classified_by="hint",
            user_text=user_text,
        )
    else:
        intent = await container.classifier.classify(messages, container.config.task_types)

    # ── 2. Model selection ──
    _prov_fields = {f.name for f in ProviderConfig.__dataclass_fields__.values()}
    providers: dict[str, ProviderConfig] = {
        k: ProviderConfig(**{fk: fv for fk, fv in v.items() if fk in _prov_fields})
        if isinstance(v, dict)
        else v
        for k, v in container.config.providers.items()
    }

    _model_fields = {f.name for f in ModelConfig.__dataclass_fields__.values()}
    models: dict[str, ModelConfig] = {
        k: ModelConfig(**{fk: fv for fk, fv in v.items() if fk in _model_fields})
        if isinstance(v, dict)
        else v
        for k, v in container.config.models.items()
    }

    try:
        selection = container.router.select(intent, models, providers, container.config.routing)
    except Exception:
        logger.warning("Router selection failed in debug endpoint", exc_info=True)
        selection = None

    # ── 3. Build explanation ──
    if selection is not None:
        explanation = explain_selection(selection, intent)
        candidates = explain_candidates(selection, intent)
        decision = selection.model_id
    else:
        explanation = (
            f"{intent.task_type.capitalize()} task detected. "
            "No model could be selected — routing failed."
        )
        candidates = []
        decision = "none"

    return JSONResponse(
        content={
            "intent": {
                "task_type": intent.task_type,
                "complexity": intent.complexity,
                "priority": intent.priority,
                "classified_by": intent.classified_by,
                "keyword_score": intent.keyword_score,
            },
            "candidates": candidates,
            "decision": decision,
            "explanation": explanation,
        }
    )
