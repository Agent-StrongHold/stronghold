"""Gate endpoint for red team regression workflow."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.security.gate import Gate

router = APIRouter(prefix="/v1/stronghold/gate")

def _get_gate(request: Request) -> Gate:
    """Get the Gate instance from the container."""
    container = request.app.state.container
    return container.gate

@router.post("")
async def gate_endpoint(
    request: Request,
    gate: Gate = Depends(_get_gate),
) -> JSONResponse:
    """Red team regression gate endpoint.

    Processes red team benchmark requests and enforces detection rate policies.
    """
    body: dict[str, Any] = await request.json()

    content = body.get("content", "")
    mode = body.get("mode", "persistent")
    target_branch = body.get("target_branch")
    benchmark_suite = body.get("benchmark_suite", False)
    baseline_file = body.get("baseline_file", "tests/security/benchmark_baseline.json")
    detection_rate = body.get("detection_rate")
    mutation_enabled = body.get("mutation_enabled", False)
    baseline_commit = body.get("baseline_commit", False)
    simulate_permission_error = body.get("simulate_permission_error", False)

    # Process the gate request
    result = await gate.process_red_team_request(
        content=content,
        mode=mode,
        target_branch=target_branch,
        benchmark_suite=benchmark_suite,
        baseline_file=baseline_file,
        detection_rate=detection_rate,
        mutation_enabled=mutation_enabled,
        baseline_commit=baseline_commit,
        simulate_permission_error=simulate_permission_error,
    )

    return JSONResponse(content=result)

@router.post("/redteam/ci")
async def redteam_ci_gate(
    request: Request,
    gate: Gate = Depends(_get_gate),
) -> JSONResponse:
    """CI integration endpoint for red team regression gate.

    This endpoint is used by CI workflows to run red team benchmarks
    and enforce detection rate policies before merging PRs.
    """
    body: dict[str, Any] = await request.json()

    content = body.get("content", "")
    mode = body.get("mode", "persistent")
    target_branch = body.get("target_branch")
    benchmark_suite = body.get("benchmark_suite", True)
    baseline_file = body.get("baseline_file", "tests/security/benchmark_baseline.json")
    detection_rate = body.get("detection_rate")

    # Process the gate request
    result = await gate.process_red_team_request(
        content=content,
        mode=mode,
        target_branch=target_branch,
        benchmark_suite=benchmark_suite,
        baseline_file=baseline_file,
        detection_rate=detection_rate,
    )

    return JSONResponse(content=result)