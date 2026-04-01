"""OpenAI-compatible embeddings endpoint.

POST /v1/embeddings — accepts {input, model}, returns OpenAI-format response.
Auth required.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("stronghold.api.embeddings")

router = APIRouter()


@router.post("/v1/embeddings")
async def create_embeddings(request: Request) -> dict[str, Any]:
    """Create embeddings for the given input text(s).

    OpenAI-compatible: accepts ``{input, model}`` where ``input`` is a string
    or list of strings. Returns ``{object, data, model, usage}``.
    """
    container = request.app.state.container

    # --- Auth ---
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    # --- Parse body ---
    body = await request.json()
    raw_input = body.get("input")
    model = body.get("model", "text-embedding-3-small")

    if raw_input is None:
        raise HTTPException(status_code=400, detail="Missing 'input' field")

    # Normalize to list[str]
    if isinstance(raw_input, str):
        texts: list[str] = [raw_input]
    elif isinstance(raw_input, list):
        texts = [str(t) for t in raw_input]
    else:
        raise HTTPException(status_code=400, detail="'input' must be a string or list of strings")

    if not texts:
        raise HTTPException(status_code=400, detail="'input' must not be empty")

    # --- Get embedding client ---
    embedding_client = getattr(container, "embedding_client", None)
    if embedding_client is None:
        raise HTTPException(status_code=501, detail="Embedding client not configured")

    # --- Compute embeddings ---
    vectors = await embedding_client.embed_batch(texts)

    # --- Build OpenAI-compatible response ---
    data: list[dict[str, Any]] = [
        {
            "object": "embedding",
            "embedding": vec,
            "index": idx,
        }
        for idx, vec in enumerate(vectors)
    ]

    total_tokens = sum(len(t.split()) for t in texts)

    return {
        "object": "list",
        "data": data,
        "model": model,
        "usage": {
            "prompt_tokens": total_tokens,
            "total_tokens": total_tokens,
        },
    }
