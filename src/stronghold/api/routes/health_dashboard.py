"""API routes: model health dashboard — real-time provider/model status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


async def _require_auth(request: Request) -> Any:
    """Authenticate the request. Returns AuthContext."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth: Any = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return auth


@router.get("/v1/stronghold/health/providers")
async def provider_health(request: Request) -> list[dict[str, Any]]:
    """Per-provider health status: name, is_healthy, error_rate, avg_latency_ms, last_error_at."""
    await _require_auth(request)
    container = request.app.state.container
    monitor = getattr(container, "health_monitor", None)
    if monitor is None:
        return []
    result: list[dict[str, Any]] = monitor.get_provider_health()
    return result


@router.get("/v1/stronghold/health/models")
async def model_health(request: Request) -> list[dict[str, Any]]:
    """Per-model health: name, provider, avg_latency_ms, tool_success_rate, request_count."""
    await _require_auth(request)
    container = request.app.state.container
    monitor = getattr(container, "health_monitor", None)
    if monitor is None:
        return []
    result: list[dict[str, Any]] = monitor.get_model_health()
    return result


@router.get("/v1/stronghold/health/circuit-breakers")
async def circuit_breaker_status(request: Request) -> list[dict[str, Any]]:
    """Circuit breaker states per provider (if integrated).

    Returns empty list when no circuit breakers are configured.
    Future: will integrate with the router's fallback/retry logic.
    """
    await _require_auth(request)
    container = request.app.state.container
    monitor = getattr(container, "health_monitor", None)
    if monitor is None:
        return []

    # Derive circuit breaker state from provider health:
    # CLOSED (healthy), OPEN (unhealthy), HALF_OPEN (recovering)
    result: list[dict[str, Any]] = []
    for provider in monitor.get_provider_health():
        if provider["is_healthy"]:
            state = "CLOSED"
        elif provider["error_rate"] >= 0.9:
            state = "OPEN"
        else:
            state = "HALF_OPEN"

        result.append(
            {
                "provider": provider["name"],
                "state": state,
                "error_rate": provider["error_rate"],
                "request_count": provider["request_count"],
            }
        )
    return result
