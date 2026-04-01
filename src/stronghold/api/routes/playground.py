"""API route: playground — test prompt changes before promoting.

All endpoints require admin authentication.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.playground.runner import PlaygroundRunner

router = APIRouter(prefix="/v1/stronghold/playground")


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


@router.post("/run")
async def playground_run(request: Request) -> JSONResponse:
    """Test a single prompt against the LLM."""
    await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    system_prompt = body.get("system_prompt")
    if not system_prompt:
        raise HTTPException(status_code=400, detail="'system_prompt' is required")

    test_messages: list[dict[str, Any]] = body.get("test_messages", [])
    model: str = body.get("model", "auto")

    runner = PlaygroundRunner(
        llm=container.llm,
        prompt_manager=container.prompt_manager,
    )
    result = await runner.run(
        system_prompt=system_prompt,
        test_messages=test_messages,
        model=model,
    )
    return JSONResponse(content=asdict(result))


@router.post("/compare")
async def playground_compare(request: Request) -> JSONResponse:
    """Compare test prompt vs production prompt side-by-side."""
    await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    test_prompt = body.get("test_prompt")
    production_prompt = body.get("production_prompt")
    if not test_prompt or not production_prompt:
        raise HTTPException(
            status_code=400,
            detail="'test_prompt' and 'production_prompt' are required",
        )

    test_messages: list[dict[str, Any]] = body.get("test_messages", [])
    model: str = body.get("model", "auto")

    runner = PlaygroundRunner(
        llm=container.llm,
        prompt_manager=container.prompt_manager,
    )
    comparison = await runner.compare(
        test_prompt=test_prompt,
        production_prompt=production_prompt,
        test_messages=test_messages,
        model=model,
    )
    return JSONResponse(
        content={
            "test_result": asdict(comparison.test_result),
            "production_result": asdict(comparison.production_result)
            if comparison.production_result
            else None,
        }
    )


@router.post("/suite")
async def playground_suite(request: Request) -> JSONResponse:
    """Run a batch of test cases against a system prompt."""
    await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    system_prompt = body.get("system_prompt")
    if not system_prompt:
        raise HTTPException(status_code=400, detail="'system_prompt' is required")

    test_cases: list[dict[str, Any]] = body.get("test_cases", [])
    model: str = body.get("model", "auto")

    runner = PlaygroundRunner(
        llm=container.llm,
        prompt_manager=container.prompt_manager,
    )
    results = await runner.run_suite(
        system_prompt=system_prompt,
        test_cases=test_cases,
        model=model,
    )
    return JSONResponse(content={"results": [asdict(r) for r in results]})
