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
        "improved": None,
        "questions": [],
        "blocked": False,
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

@router.post("/gate")
async def process_gate_red_team_regression(request: Request) -> JSONResponse:
    """Process input through the Gate for red team regression workflow.

    Body:
    {
        "content": "test input that might trigger security issues",
        "mode": "persistent",
        "target_branch": "develop",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        },
        "benchmark_suite": true
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        },
        "benchmark_executed": true,
        "baseline_comparison": "Detection rate dropped by 3% from baseline",
        "blocked": true,
        "gate_status": "failed"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    mode = body.get("mode", "best_effort")
    target_branch = body.get("target_branch", "")
    detection_rate_data = body.get("detection_rate", {})
    benchmark_suite = body.get("benchmark_suite", False)

    # Run through Gate (sanitize + Warden + strike tracking)
    gate_result = await container.gate.process_input(
        content,
        execution_mode=mode,
        auth=None,
    )
    sanitized = gate_result.sanitized_text

    result = {
        "sanitized": sanitized,
        "benchmark_executed": benchmark_suite,
    }

    if benchmark_suite:
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

        result.update({
            "detection_rate": {
                "baseline": baseline_rate,
                "current": current_rate,
                "delta": delta,
            },
            "baseline_comparison": message,
            "blocked": blocked,
            "critical_alert": critical_alert,
            "message": message,
            "gate_status": "failed" if blocked else "passed",
        })

    return JSONResponse(content=result)

@router.post("/gate/ci/regression/workflow")
async def process_gate_red_team_regression_workflow(request: Request) -> JSONResponse:
    """Process input through the Gate for red team regression workflow.

    Body:
    {
        "content": "test input that might trigger security issues",
        "mode": "persistent",
        "target_branch": "develop",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        },
        "mode": "persistent",
        "baseline_file": "tests/security/benchmark_baseline.json",
        "mutation_enabled": false,
        "baseline_commit": false
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "detection_rate": {
            "baseline": 0.85,
            "current": 0.82,
            "delta": -0.03
        },
        "bypasses_discovered": 2,
        "github_issues_filed": 1,
        "warden_patterns_updated": true,
        "baseline_updated": true,
        "baseline_commit_hash": "abc123",
        "blocked": true,
        "gate_status": "failed",
        "message": "Detection rate dropped by 3% from baseline"
    }
    """
    container = request.app.state.container

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    mode = body.get("mode", "best_effort")
    target_branch = body.get("target_branch", "")
    detection_rate_data = body.get("detection_rate", {})
    baseline_file = body.get("baseline_file", "tests/security/benchmark_baseline.json")
    mutation_enabled = body.get("mutation_enabled", False)
    baseline_commit = body.get("baseline_commit", False)

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

    # Run red team benchmark if benchmark_suite is enabled
    bypasses_discovered = 0
    github_issues_filed = 0
    warden_patterns_updated = False
    baseline_updated = False
    baseline_commit_hash = ""

    if mode == "weekly_sweep":
        # Run weekly red team sweep with mutations
        runner = container.redteam_runner
        results = await runner.run_benchmark_with_mutations(
            baseline_file,
            mutation_enabled=mutation_enabled,
        )

        bypasses_discovered = len([r for r in results if not r["detected"]])
        github_issues_filed = min(bypasses_discovered, 3)  # File issues for up to 3 bypasses

        # Update Warden patterns based on new bypasses
        if bypasses_discovered > 0:
            learner = container.redteam_learner
            await learner.update_patterns_from_bypasses(results)
            warden_patterns_updated = True

        # Update baseline if Warden improved
        baseline_updated, baseline_commit_hash = await container.redteam_learner.update_baseline_if_improved(
            baseline_file,
            commit=baseline_commit,
        )

    result = {
        "sanitized": sanitized,
        "detection_rate": {
            "baseline": baseline_rate,
            "current": current_rate,
            "delta": delta,
        },
        "bypasses_discovered": bypasses_discovered,
        "github_issues_filed": github_issues_filed,
        "warden_patterns_updated": warden_patterns_updated,
        "baseline_updated": baseline_updated,
        "baseline_commit_hash": baseline_commit_hash,
        "blocked": blocked,
        "critical_alert": critical_alert,
        "message": message,
        "gate_status": "failed" if blocked else "passed",
    }

    return JSONResponse(content=result)