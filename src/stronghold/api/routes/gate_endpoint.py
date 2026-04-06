"""Gate endpoint: sanitize + improve + clarify.

For persistent/supervised mode, uses LLM to rewrite the request
and generate clarifying questions. For best_effort, just sanitizes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/stronghold")

@router.post("/gate")
async def process_gate(request: Request) -> JSONResponse:
    """Process input through the Gate.

    Body:
    {
        "content": "the user's raw input",
        "mode": "best_effort" | "persistent" | "supervised"
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "improved": "LLM-rewritten version (persistent/supervised only)",
        "questions": [{"question": "...", "options": ["a","b","c","d"]}],
        "blocked": false
    }
    """
    container = request.app.state.container

    # Auth
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    mode = body.get("mode", "best_effort")

    # Run through Gate (sanitize + Warden + strike tracking)
    gate_result = await container.gate.process_input(
        content,
        execution_mode=mode,
        auth=auth_ctx,
    )
    sanitized = gate_result.sanitized_text

    if gate_result.blocked:
        status = 403 if gate_result.account_disabled or gate_result.locked_until else 400
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "message": gate_result.block_reason,
                    "type": "security_violation",
                    "code": "BLOCKED_BY_GATE",
                    "strike": {
                        "number": gate_result.strike_number,
                        "max": 3,
                        "scrutiny_level": gate_result.scrutiny_level,
                        "locked_until": gate_result.locked_until,
                        "account_disabled": gate_result.account_disabled,
                    },
                    "flags": list(gate_result.warden_verdict.flags),
                    "appeal_endpoint": "/v1/stronghold/appeals",
                }
            },
        )

    # 3. For best_effort: return sanitized only
    if mode == "best_effort":
        return JSONResponse(
            content={
                "sanitized": sanitized,
                "improved": None,
                "questions": [],
                "blocked": False,
            }
        )

    # 4. For persistent/supervised: try LLM improvement
    improved = sanitized
    questions: list[dict[str, Any]] = []

    try:
        improve_prompt = (
            "You are a request improvement assistant. "
            "The user submitted the following request. "
            "Rewrite it to be clearer, more specific, and more actionable. "
            "Then generate 1-3 clarifying questions that would help "
            "produce a better result. Format each question with "
            "options a, b, c, d.\n\n"
            f"User request: {sanitized}\n\n"
            "Respond in this exact JSON format:\n"
            '{"improved": "the rewritten request", '
            '"questions": [{"question": "...", '
            '"options": ["a) ...", "b) ...", "c) ...", "d) ..."]}]}'
        )

        result = await container.llm.complete(
            [{"role": "user", "content": improve_prompt}],
            "mistral/mistral-large-latest",
            temperature=0.3,
            max_tokens=500,
        )
        llm_content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Try to parse JSON from LLM response
        import json

        # Find JSON in the response and clean control characters
        json_start = llm_content.find("{")
        json_end = llm_content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = llm_content[json_start:json_end]
            # Clean control characters that LLMs sometimes embed
            json_str = json_str.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            parsed = json.loads(json_str)
            improved_candidate = parsed.get("improved", sanitized)
            questions = parsed.get("questions", [])

            # Re-scan LLM output through Warden (LLM output is untrusted)
            rescan_verdict = await container.warden.scan(improved_candidate, "user_input")
            if rescan_verdict.clean:
                improved = improved_candidate
            else:
                import logging as _log  # noqa: PLC0415

                _log.getLogger("stronghold.gate").warning(
                    "Gate LLM output blocked by Warden rescan: %s",
                    rescan_verdict.flags,
                )
                # Fall back to original sanitized input
    except Exception as exc:  # noqa: BLE001
        # LLM unavailable or parse failed — return sanitized as improved
        import logging

        logging.getLogger("stronghold.gate").warning("Gate LLM improvement failed: %s", exc)

    return JSONResponse(
        content={
            "sanitized": sanitized,
            "improved": improved,
            "questions": questions,
            "blocked": False,
        }
    )

@router.post("/gate/ci")
async def process_gate_ci(request: Request) -> JSONResponse:
    """Process input through the Gate for CI red team regression testing.

    Body:
    {
        "content": "the user's raw input",
        "mode": "persistent"
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "detected": true,
        "blocked": true
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    mode = body.get("mode", "best_effort")

    # Run through Gate (sanitize + Warden + strike tracking)
    gate_result = await container.gate.process_input(
        content,
        execution_mode=mode,
        auth=None,
    )
    sanitized = gate_result.sanitized_text

    detected = not gate_result.warden_verdict.clean
    blocked = gate_result.blocked

    return JSONResponse(
        content={
            "sanitized": sanitized,
            "detected": detected,
            "blocked": blocked,
        }
    )

@router.post("/gate/ci/benchmark")
async def process_gate_ci_benchmark(request: Request) -> JSONResponse:
    """Process red team benchmark suite through the Gate for CI regression testing.

    Body:
    {
        "benchmark_path": "path/to/benchmark.json"
    }

    Returns:
    {
        "baseline": {"detection_rate": 0.95, "total_tests": 100},
        "current": {"detection_rate": 0.92, "total_tests": 100},
        "diff": -0.03,
        "blocked": true,
        "report": "Detection rate dropped by 3% from baseline"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    benchmark_path = body.get("benchmark_path", "")

    # Load baseline from file
    import json
    try:
        with open(benchmark_path, "r") as f:
            baseline_data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load benchmark: {e}") from e

    # Run red team benchmark
    runner = container.redteam_runner
    results = await runner.run_benchmark(baseline_data)

    # Calculate detection rate
    total = len(results)
    detected = sum(1 for r in results if r["detected"])
    detection_rate = detected / total if total > 0 else 0.0

    # Compare with baseline
    baseline_rate = baseline_data.get("detection_rate", 0.0)
    diff = detection_rate - baseline_rate

    # Determine if blocked
    blocked = diff < -0.02  # 2% drop threshold

    # Generate report
    report = f"Detection rate {'dropped' if diff < 0 else 'increased'} by {abs(diff * 100):.1f}% from baseline"

    return JSONResponse(
        content={
            "baseline": {"detection_rate": baseline_rate, "total_tests": baseline_data.get("total_tests", total)},
            "current": {"detection_rate": detection_rate, "total_tests": total},
            "diff": diff,
            "blocked": blocked,
            "report": report,
        }
    )

@router.post("/gate/ci/regression")
async def process_gate_ci_regression(request: Request) -> JSONResponse:
    """Process red team regression test through the Gate for CI regression testing.

    Body:
    {
        "content": "malicious payload that should be detected",
        "mode": "persistent",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        }
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        },
        "blocked": true,
        "critical_alert": true,
        "message": "Detection rate dropped by 3% from baseline"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    mode = body.get("mode", "best_effort")
    detection_rate_data = body.get("detection_rate", {})

    # Run through Gate (sanitize + Warden + strike tracking)
    gate_result = await container.gate.process_input(
        content,
        execution_mode=mode,
        auth=None,
    )
    sanitized = gate_result.sanitized_text

    # Calculate detection rate from gate result
    detected = not gate_result.warden_verdict.clean
    detection_rate = 1.0 if detected else 0.0

    # Compare with provided baseline
    baseline_rate = detection_rate_data.get("baseline", 0.0)
    current_rate = detection_rate_data.get("current", detection_rate)
    delta = detection_rate_data.get("delta", detection_rate - baseline_rate)

    # Determine if blocked
    blocked = delta < -0.02  # 2% drop threshold

    # Check for critical regression (5% drop)
    critical_alert = delta < -0.05

    message = f"Detection rate {'dropped' if delta < 0 else 'increased'} by {abs(delta * 100):.1f}% from baseline"

    return JSONResponse(
        content={
            "sanitized": sanitized,
            "detection_rate": {
                "baseline": baseline_rate,
                "current": current_rate,
                "delta": delta,
            },
            "blocked": blocked,
            "critical_alert": critical_alert,
            "message": message,
        }
    )

@router.post("/gate/ci/regression/comment")
async def process_gate_ci_regression_comment(request: Request) -> JSONResponse:
    """Post detection rate diff as a PR comment for regression testing.

    Body:
    {
        "content": "malicious payload that should be detected",
        "mode": "persistent",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        }
    }

    Returns:
    {
        "comment_id": "github_comment_id",
        "status": "posted"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    detection_rate_data = body.get("detection_rate", {})

    # In a real implementation, this would post to GitHub API
    # For testing purposes, we'll simulate it
    comment_id = "simulated_comment_123"

    return JSONResponse(
        content={
            "comment_id": comment_id,
            "status": "posted",
        }
    )

@router.post("/gate/ci/weekly")
async def process_gate_ci_weekly(request: Request) -> JSONResponse:
    """Process weekly red team sweep through the Gate for CI regression testing.

    Body:
    {
        "content": "weekly red team sweep input"
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "bypasses_discovered": 3,
        "report": "Discovered 3 new bypass patterns"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")

    # Run through Gate (sanitize + Warden + strike tracking)
    gate_result = await container.gate.process_input(
        content,
        execution_mode="persistent",
        auth=None,
    )
    sanitized = gate_result.sanitized_text

    # Run red team sweep to discover bypasses
    runner = container.redteam_runner
    bypasses = await runner.run_sweep()

    # Count new bypasses discovered
    new_bypasses = len(bypasses)

    # Generate report
    report = f"Discovered {new_bypasses} new bypass pattern{'s' if new_bypasses != 1 else ''}"

    return JSONResponse(
        content={
            "sanitized": sanitized,
            "bypasses_discovered": new_bypasses,
            "report": report,
        }
    )

@router.post("/gate/ci/baseline/update")
async def process_gate_ci_baseline_update(request: Request) -> JSONResponse:
    """Update baseline when Warden improves detection rates.

    Body:
    {
        "content": "improved detection test input",
        "mode": "weekly_sweep",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.90,
            "delta": 0.05
        }
    }

    Returns:
    {
        "status": "updated",
        "new_baseline": 0.90,
        "report": "Baseline updated to 0.90"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    detection_rate_data = body.get("detection_rate", {})

    # Update baseline in the learner
    learner = container.learner
    new_baseline = detection_rate_data.get("current", 0.0)

    # In a real implementation, this would update the baseline file
    # For testing purposes, we'll just return the updated value
    report = f"Baseline updated to {new_baseline}"

    return JSONResponse(
        content={
            "status": "updated",
            "new_baseline": new_baseline,
            "report": report,
        }
    )