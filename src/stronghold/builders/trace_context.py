"""TraceContext: immutable propagation record for builders workflow tracing.

Built once at workflow start, enriched via functional update (.with_()) as
execution descends through stages → criteria → LLM calls → tool calls.
Every span produced by the workflow gets its attributes from ctx.to_span_attrs().

See ARCHITECTURE.md §7.4 and the plan at .claude/plans/ for the full
identity model (session scoping, agent_id namespace, trace-level vs span-level).
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from typing import Any

__all__ = ["TraceContext", "parse_traceparent"]


@dataclass(frozen=True)
class TraceContext:
    """Immutable tracing context propagated through every layer of a builders run.

    Trace-level fields are set once at workflow start.
    Span-level fields are enriched via .with_() at each layer boundary.
    """

    # ── Trace-level (set once at workflow start) ─────────────────────
    run_id: str
    user_id: str
    org_id: str
    auth_method: str
    session_id: str
    intent_mode: str
    parent_trace_id: str
    request_id: str
    repo: str
    issue_number: int
    branch: str
    workspace_ref: str
    runtime_version: str
    issue_type: str = ""
    is_ui: bool = False
    deployment_env: str = ""
    service_name: str = "stronghold.builders"
    service_version: str = ""

    # ── Span-level (varies as execution descends) ────────────────────
    agent_id: str = ""
    agent_kind: str = ""
    stage: str = ""
    outer_loop: int = -1
    stage_attempt: int = -1
    step_in_stage: str = ""
    criterion_index: int = -1
    criterion_text: str = ""
    model_name: str = ""
    model_role: str = ""
    prompt_name: str = ""
    prompt_version: str = ""
    extractor_name: str = ""
    tool_name: str = ""
    tool_action: str = ""

    # NOTE: model_params, model_fallback_chain, tool_params, tool_payload_*,
    # tool_result_*, tool_status, input_tokens, output_tokens, cost_usd are
    # NOT on TraceContext. They are computed AT the span call site and passed
    # directly to span.set_attributes() merged with ctx.to_span_attrs().

    def with_(self, **updates: Any) -> TraceContext:
        """Return a new TraceContext with the given fields updated."""
        return dataclasses.replace(self, **updates)

    def to_trace_metadata(self) -> dict[str, Any]:
        """Trace-level fields only, suitable for tracer.create_trace(metadata=...)."""
        return {
            "run_id": self.run_id,
            "intent_mode": self.intent_mode,
            "request_id": self.request_id,
            "repo": self.repo,
            "issue_number": self.issue_number,
            "branch": self.branch,
            "workspace_ref": self.workspace_ref,
            "runtime_version": self.runtime_version,
            "issue_type": self.issue_type,
            "is_ui": self.is_ui,
            "deployment_env": self.deployment_env,
            "service_name": self.service_name,
            "service_version": self.service_version,
            "auth_method": self.auth_method,
            "org_id": self.org_id,
        }

    def to_span_attrs(self) -> dict[str, Any]:
        """All non-empty fields, suitable for span.set_attributes(...).

        Filters sentinel values (-1, "") so Phoenix attribute lists stay clean.
        False and 0 are preserved (they're valid, not sentinels).
        """
        out: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if v == "" or v == -1:
                continue
            out[f.name] = v
        return out


# ── W3C Trace Context parsing ────────────────────────────────────────

_TRACEPARENT_RE = re.compile(
    r"^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$"
)


def parse_traceparent(value: str) -> str:
    """Parse W3C traceparent header. Returns trace_id or '' on error.

    Format: ``00-<32hex trace_id>-<16hex span_id>-<2hex flags>``
    Invalid or missing values return '' (never raises).
    """
    if not value:
        return ""
    match = _TRACEPARENT_RE.match(value.strip())
    if not match:
        return ""
    trace_id = match.group(1)
    # All-zero trace_id is invalid per W3C spec
    if trace_id == "0" * 32:
        return ""
    return trace_id
