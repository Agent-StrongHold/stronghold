"""Warden-at-Arms: API discovery + risk classification strategy.

Parses an OpenAPI-like spec (JSON dict), classifies each endpoint by
HTTP-method risk level, and generates skill definitions.  When no spec
is provided, falls back to a ReAct-style LLM call.

Risk levels:
  low    — read-only methods (GET, HEAD, OPTIONS)
  medium — state-changing methods (POST, PUT, PATCH) on safe paths
  high   — destructive methods (DELETE) or destructive path keywords
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.agents.warden_at_arms.strategy")

# HTTP methods considered read-only (low risk).
_READ_ONLY_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

# HTTP methods that are always high risk regardless of path.
_DESTRUCTIVE_METHODS: frozenset[str] = frozenset({"DELETE"})

# Path segments that elevate a state-changing method to high risk.
_DESTRUCTIVE_PATH_KEYWORDS: frozenset[str] = frozenset(
    {
        "purge",
        "destroy",
        "drop",
        "reset",
        "truncate",
        "wipe",
        "erase",
        "nuke",
    }
)


def classify_endpoint(method: str, path: str) -> str:
    """Classify a single endpoint by risk level.

    Returns ``"low"``, ``"medium"``, or ``"high"``.
    """
    upper_method = method.upper()

    if upper_method in _READ_ONLY_METHODS:
        return "low"

    if upper_method in _DESTRUCTIVE_METHODS:
        return "high"

    # State-changing method — check path for destructive keywords.
    path_lower = path.lower()
    for keyword in _DESTRUCTIVE_PATH_KEYWORDS:
        if keyword in path_lower:
            return "high"

    return "medium"


def discover_api(spec_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract and classify endpoints from an OpenAPI-like spec.

    Each returned dict contains:
      method  — HTTP method (uppercased)
      path    — URL path template
      risk    — "low", "medium", or "high"
      summary — operation summary (empty string if absent)
    """
    paths: dict[str, Any] = spec_dict.get("paths", {})
    endpoints: list[dict[str, Any]] = []

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            upper_method = method.upper()
            summary = ""
            if isinstance(operation, dict):
                summary = operation.get("summary", "")

            risk = classify_endpoint(upper_method, path)
            endpoints.append(
                {
                    "method": upper_method,
                    "path": path,
                    "risk": risk,
                    "summary": summary,
                }
            )

    return endpoints


def _format_discovery_report(endpoints: list[dict[str, Any]]) -> str:
    """Build a human-readable discovery report from classified endpoints."""
    low = [ep for ep in endpoints if ep["risk"] == "low"]
    medium = [ep for ep in endpoints if ep["risk"] == "medium"]
    high = [ep for ep in endpoints if ep["risk"] == "high"]

    lines: list[str] = [
        f"API Discovery: {len(endpoints)} endpoints found",
        f"  Low risk:    {len(low)}",
        f"  Medium risk: {len(medium)}",
        f"  High risk:   {len(high)}",
        "",
    ]

    for label, group in [("LOW", low), ("MEDIUM", medium), ("HIGH", high)]:
        if group:
            lines.append(f"--- {label} risk ---")
            for ep in group:
                desc = f"  {ep['summary']}" if ep["summary"] else ""
                lines.append(f"  {ep['method']} {ep['path']}{desc}")
            lines.append("")

    return "\n".join(lines)


class WardenAtArmsStrategy:
    """API discovery and risk classification strategy.

    When an OpenAPI-like ``spec`` is provided (via kwargs), the strategy
    parses it deterministically, classifies endpoints by risk, and returns
    a structured report.  The LLM is then called to produce an analysis
    summary.

    When no spec is given, falls back to a single LLM call (ReAct-style
    entry point for runtime execution).
    """

    def __init__(self, max_rounds: int = 5) -> None:
        self.max_rounds = max_rounds

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any = None,
        trace: Trace | None = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Run API discovery if a spec is provided, else fall back to LLM."""
        spec: dict[str, Any] | None = kwargs.get("spec")

        # If a spec is given, do deterministic discovery first.
        if spec is not None:
            endpoints = discover_api(spec)

            if endpoints:
                report = _format_discovery_report(endpoints)
                logger.info(
                    "Warden-at-Arms discovered %d endpoints from spec",
                    len(endpoints),
                )

                # Ask the LLM to produce an analysis of the discovered endpoints.
                analysis_messages = list(messages)
                analysis_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "I've performed API discovery. Here is the report:\n\n"
                            f"{report}\n\n"
                            "Provide a brief security analysis of these endpoints."
                        ),
                    }
                )

                if trace:
                    with trace.span("warden_at_arms.analysis") as span:
                        span.set_input({"endpoint_count": len(endpoints)})
                        response = await llm.complete(analysis_messages, model)
                        usage = response.get("usage", {})
                        span.set_usage(
                            input_tokens=usage.get("prompt_tokens", 0),
                            output_tokens=usage.get("completion_tokens", 0),
                            model=model,
                        )
                else:
                    response = await llm.complete(analysis_messages, model)
                    usage = response.get("usage", {})

                choices = response.get("choices", [])
                choice = choices[0] if choices else {}
                llm_analysis: str = choice.get("message", {}).get("content", "")

                combined = f"{report}\n{llm_analysis}"

                return ReasoningResult(
                    response=combined,
                    done=True,
                    reasoning_trace=(
                        f"Warden-at-Arms: discovered {len(endpoints)} endpoints "
                        f"(low={len([e for e in endpoints if e['risk'] == 'low'])}, "
                        f"medium={len([e for e in endpoints if e['risk'] == 'medium'])}, "
                        f"high={len([e for e in endpoints if e['risk'] == 'high'])})"
                    ),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                )

        # No spec or empty spec — fall back to plain LLM call.
        if trace:
            with trace.span("warden_at_arms.fallback") as span:
                span.set_input({"model": model, "message_count": len(messages)})
                response = await llm.complete(messages, model, tools=tools)
                usage = response.get("usage", {})
                span.set_usage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=model,
                )
        else:
            response = await llm.complete(messages, model, tools=tools)
            usage = response.get("usage", {})

        choices = response.get("choices", [])
        choice = choices[0] if choices else {}
        content: str = choice.get("message", {}).get("content", "")

        return ReasoningResult(
            response=content,
            done=True,
            reasoning_trace="Warden-at-Arms: LLM fallback (no spec provided)",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
