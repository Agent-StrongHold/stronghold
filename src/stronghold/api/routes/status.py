"""Status and health endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from stronghold import __version__

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Health check — no auth required (load balancer probe).

    Checks database and LLM connectivity. Returns 200 even if degraded
    (so load balancers don't kill the container), but body indicates issues.
    """
    result: dict[str, Any] = {
        "status": "ok",
        "service": "stronghold",
        "version": __version__,
    }

    # Database check
    container = getattr(request.app.state, "container", None)
    if container and getattr(container, "db_pool", None):
        try:
            async with container.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            result["db"] = "connected"
        except Exception:  # noqa: BLE001
            result["db"] = "error"
            result["status"] = "degraded"
    else:
        result["db"] = "in_memory"

    # LLM proxy check (only for real LiteLLMClient with a base_url)
    llm_url = getattr(getattr(container, "llm", None), "_base_url", None) if container else None
    if llm_url:
        import httpx  # noqa: PLC0415

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{llm_url}/health")
                result["llm"] = "reachable" if resp.status_code < 500 else "unhealthy"
        except Exception:  # noqa: BLE001
            result["llm"] = "unreachable"
            result["status"] = "degraded"

    return result


@router.get("/status/reactor")
async def reactor_status(request: Request) -> dict[str, Any]:
    """Reactor loop status — triggers, events, stats. Requires auth."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    status = container.reactor.get_status()
    return {
        "running": status.running,
        "tick_count": status.tick_count,
        "active_tasks": status.active_tasks,
        "events_processed": status.events_processed,
        "triggers_fired": status.triggers_fired,
        "tasks_completed": status.tasks_completed,
        "tasks_failed": status.tasks_failed,
        "triggers": status.triggers,
        "recent_events": status.recent_events,
    }


@router.get("/version")
async def version() -> dict[str, Any]:
    """Version endpoint — returns current Stronghold version and Python version."""
    import sys  # noqa: PLC0415

    return {
        "version": __version__,
        "python_version": sys.version,
        "service": "stronghold",
    }


@router.get("/v1/stronghold/version")
async def version_v1() -> dict[str, Any]:
    """Version endpoint — returns current Stronghold version and Python version."""
    import sys  # noqa: PLC0415

    return {
        "version": __version__,
        "python_version": sys.version,
        "service": "stronghold",
    }


@router.post("/v1/stronghold/gate/red-team-regression")
async def red_team_regression_gate(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Red team regression gate endpoint."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    benchmark_results = payload.get("benchmark_results", {})
    threshold = payload.get("threshold", 0.9)

    score = benchmark_results.get("score", 0)
    if score > threshold:
        raise HTTPException(status_code=400, detail="Benchmark score exceeds allowed threshold")

    # Check for baseline in container
    baseline = getattr(container, "red_team_baseline", None)
    if baseline is None:
        raise HTTPException(status_code=400, detail="Baseline not configured")

    return {"status": "passed", "score": score, "threshold": threshold}


@router.post("/v1/stronghold/gate/red-team-regression")
async def red_team_regression_gate_legacy(
    request: Request, payload: dict[str, Any]
) -> dict[str, Any]:
    """Red team regression gate endpoint - legacy path for backward compatibility."""
    return await red_team_regression_gate(request, payload)
