"""API route: model comparison — side-by-side evaluation."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.evaluation.compare import ModelComparator

logger = logging.getLogger("stronghold.api.compare")

router = APIRouter()

_MAX_MODELS = 5


@router.post("/v1/stronghold/compare/models")
async def compare_models(request: Request) -> JSONResponse:
    """Compare 2+ models on the same prompt in parallel (admin-only)."""
    container = request.app.state.container

    # ── Auth: require admin ──
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")

    # ── Parse body ──
    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    models: list[str] = body.get("models", [])
    task_type: str = body.get("task_type", "")

    # ── Validate ──
    if len(models) > _MAX_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {_MAX_MODELS} models per comparison",
        )

    # ── Run comparison ──
    comparator = ModelComparator(container.llm)
    result = await comparator.compare(messages, models, task_type=task_type)

    return JSONResponse(content=asdict(result))
