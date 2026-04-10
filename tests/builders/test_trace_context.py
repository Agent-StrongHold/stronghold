"""Unit tests for TraceContext and parse_traceparent."""

from __future__ import annotations

from stronghold.builders.trace_context import TraceContext, parse_traceparent


def _base_ctx(**overrides: object) -> TraceContext:
    """Minimal valid TraceContext for testing."""
    defaults = {
        "run_id": "run-test",
        "user_id": "user-1",
        "org_id": "org-1",
        "auth_method": "service",
        "session_id": "sess-1",
        "intent_mode": "autonomous_build",
        "parent_trace_id": "",
        "request_id": "req-1",
        "repo": "owner/repo",
        "issue_number": 42,
        "branch": "mason/42",
        "workspace_ref": "ws-1",
        "runtime_version": "v1",
    }
    defaults.update(overrides)
    return TraceContext(**defaults)  # type: ignore[arg-type]


# ── with_() immutability ─────────────────────────────────────────────


class TestWith:
    def test_returns_new_instance(self) -> None:
        ctx = _base_ctx()
        ctx2 = ctx.with_(stage="acceptance_defined")
        assert ctx.stage == ""  # original unchanged
        assert ctx2.stage == "acceptance_defined"

    def test_combines_multiple_fields(self) -> None:
        ctx = _base_ctx()
        ctx2 = ctx.with_(stage="tdd", agent_id="mason", outer_loop=1)
        assert ctx2.stage == "tdd"
        assert ctx2.agent_id == "mason"
        assert ctx2.outer_loop == 1

    def test_preserves_existing_fields(self) -> None:
        ctx = _base_ctx(intent_mode="autonomous_build")
        ctx2 = ctx.with_(stage="x")
        assert ctx2.intent_mode == "autonomous_build"
        assert ctx2.run_id == "run-test"

    def test_immutability_on_assignment(self) -> None:
        ctx = _base_ctx()
        import dataclasses
        try:
            ctx.stage = "x"  # type: ignore[misc]
            assert False, "Should have raised FrozenInstanceError"
        except dataclasses.FrozenInstanceError:
            pass


# ── to_trace_metadata ────────────────────────────────────────────────


class TestToTraceMetadata:
    def test_includes_trace_level_fields(self) -> None:
        ctx = _base_ctx()
        md = ctx.to_trace_metadata()
        for field in ["run_id", "intent_mode", "repo", "issue_number",
                       "branch", "workspace_ref", "runtime_version",
                       "deployment_env", "service_name", "org_id"]:
            assert field in md, f"missing {field}"

    def test_excludes_span_level_fields(self) -> None:
        ctx = _base_ctx(agent_id="mason", stage="tdd", criterion_index=3)
        md = ctx.to_trace_metadata()
        assert "agent_id" not in md
        assert "stage" not in md
        assert "criterion_index" not in md


# ── to_span_attrs ────────────────────────────────────────────────────


class TestToSpanAttrs:
    def test_excludes_empty_strings(self) -> None:
        ctx = _base_ctx(agent_id="", stage="")
        attrs = ctx.to_span_attrs()
        assert "agent_id" not in attrs
        assert "stage" not in attrs

    def test_excludes_sentinel_negative_one(self) -> None:
        ctx = _base_ctx(criterion_index=-1, outer_loop=-1)
        attrs = ctx.to_span_attrs()
        assert "criterion_index" not in attrs
        assert "outer_loop" not in attrs

    def test_includes_zero(self) -> None:
        ctx = _base_ctx(criterion_index=0)
        attrs = ctx.to_span_attrs()
        assert "criterion_index" in attrs
        assert attrs["criterion_index"] == 0

    def test_includes_false(self) -> None:
        ctx = _base_ctx(is_ui=False)
        attrs = ctx.to_span_attrs()
        assert "is_ui" in attrs
        assert attrs["is_ui"] is False

    def test_includes_non_empty_fields(self) -> None:
        ctx = _base_ctx(agent_id="mason", stage="tdd")
        attrs = ctx.to_span_attrs()
        assert attrs["agent_id"] == "mason"
        assert attrs["stage"] == "tdd"

    def test_full_round_trip(self) -> None:
        """Build a ctx, enrich it through layers, verify attrs."""
        ctx = _base_ctx()
        ctx = ctx.with_(agent_id="frank", agent_kind="build_worker", stage="issue_analyzed")
        ctx = ctx.with_(outer_loop=0, stage_attempt=1)
        ctx = ctx.with_(model_name="opus-4", model_role="frank", prompt_name="builders.frank.analyze_issue")
        attrs = ctx.to_span_attrs()
        assert attrs["agent_id"] == "frank"
        assert attrs["outer_loop"] == 0
        assert attrs["model_name"] == "opus-4"
        assert attrs["run_id"] == "run-test"  # trace-level preserved


# ── parse_traceparent ────────────────────────────────────────────────


class TestParseTraceparent:
    def test_valid(self) -> None:
        result = parse_traceparent("00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01")
        assert result == "0af7651916cd43dd8448eb211c80319c"

    def test_invalid_version(self) -> None:
        assert parse_traceparent("01-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01") == ""

    def test_wrong_part_count(self) -> None:
        assert parse_traceparent("00-abc-def") == ""

    def test_short_trace_id(self) -> None:
        assert parse_traceparent("00-abc-b7ad6b7169203331-01") == ""

    def test_non_hex_trace_id(self) -> None:
        assert parse_traceparent("00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-b7ad6b7169203331-01") == ""

    def test_all_zero_trace_id(self) -> None:
        assert parse_traceparent("00-00000000000000000000000000000000-b7ad6b7169203331-01") == ""

    def test_empty_string(self) -> None:
        assert parse_traceparent("") == ""

    def test_whitespace(self) -> None:
        result = parse_traceparent("  00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01  ")
        assert result == "0af7651916cd43dd8448eb211c80319c"
