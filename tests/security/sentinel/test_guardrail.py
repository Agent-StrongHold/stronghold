"""Tests for SentinelGuardrail — unified guardrail chaining validation, PII, and tokens.

14+ tests covering:
  - pre_call validates arguments against schema
  - pre_call repairs hallucinated arguments (fuzzy enum, type coercion, defaults)
  - pre_call passes through when no schema given
  - pre_call audit logging
  - post_call filters PII from results
  - post_call optimizes long tokens
  - post_call passes clean results unchanged
  - post_call audit logging
  - constructor wiring
  - missing schema passes through
  - auth context propagated to audit
"""

from __future__ import annotations

from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.guardrail import SentinelGuardrail
from stronghold.security.sentinel.pii_filter import scan_and_redact
from stronghold.security.sentinel.token_optimizer import optimize_result
from stronghold.security.sentinel.validator import validate_and_repair
from stronghold.types.auth import AuthContext


def _make_auth(
    user_id: str = "user-1",
    org_id: str = "org-default",
    team_id: str = "team-default",
) -> AuthContext:
    return AuthContext(
        user_id=user_id,
        username=user_id,
        roles=frozenset({"user"}),
        org_id=org_id,
        team_id=team_id,
    )


def _make_guardrail(audit: InMemoryAuditLog | None = None) -> SentinelGuardrail:
    return SentinelGuardrail(
        validator=validate_and_repair,
        pii_filter=scan_and_redact,
        token_optimizer=optimize_result,
        audit_log=audit,
    )


def _make_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": ["query"],
    }


class TestPreCallValidates:
    """pre_call validates arguments against the provided schema."""

    async def test_valid_args_returned_unchanged(self) -> None:
        guardrail = _make_guardrail()
        result = await guardrail.pre_call(
            "web_search",
            {"query": "python tutorial"},
            schema=_make_schema(),
        )
        assert result["query"] == "python tutorial"

    async def test_missing_required_with_no_default_still_returns(self) -> None:
        """Missing required field without default is reported but args returned."""
        guardrail = _make_guardrail()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        }
        result = await guardrail.pre_call("web_search", {}, schema=schema)
        # Args returned as-is (guardrail does not block, just validates/repairs)
        assert isinstance(result, dict)


class TestPreCallRepairs:
    """pre_call repairs hallucinated arguments."""

    async def test_type_coercion_string_to_integer(self) -> None:
        """String '5' coerced to integer 5."""
        guardrail = _make_guardrail()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
            "required": ["count"],
        }
        result = await guardrail.pre_call(
            "counter",
            {"count": "5"},
            schema=schema,
        )
        assert result["count"] == 5

    async def test_fuzzy_enum_repair(self) -> None:
        """Close enum value gets fuzzy-matched."""
        guardrail = _make_guardrail()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "color": {"type": "string", "enum": ["red", "green", "blue"]},
            },
            "required": ["color"],
        }
        result = await guardrail.pre_call(
            "paint",
            {"color": "grean"},
            schema=schema,
        )
        assert result["color"] == "green"

    async def test_missing_required_with_default_repaired(self) -> None:
        """Missing required field filled with schema default."""
        guardrail = _make_guardrail()
        schema: dict[str, object] = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query", "limit"],
        }
        result = await guardrail.pre_call(
            "web_search",
            {"query": "test"},
            schema=schema,
        )
        assert result["limit"] == 10


class TestPreCallNoSchema:
    """pre_call passes through when no schema is given."""

    async def test_no_schema_passthrough(self) -> None:
        guardrail = _make_guardrail()
        args = {"foo": "bar", "baz": 42}
        result = await guardrail.pre_call("some_tool", args)
        assert result == args

    async def test_none_schema_passthrough(self) -> None:
        guardrail = _make_guardrail()
        args = {"x": 1}
        result = await guardrail.pre_call("tool", args, schema=None)
        assert result == args


class TestPreCallAudit:
    """pre_call creates audit log entries."""

    async def test_audit_entry_created_on_pre_call(self) -> None:
        audit = InMemoryAuditLog()
        guardrail = _make_guardrail(audit=audit)
        await guardrail.pre_call(
            "web_search",
            {"query": "test"},
            schema=_make_schema(),
            auth=_make_auth(),
        )
        entries = await audit.get_entries()
        assert len(entries) == 1
        assert entries[0].boundary == "pre_call"
        assert entries[0].tool_name == "web_search"

    async def test_audit_entry_includes_org_and_team(self) -> None:
        audit = InMemoryAuditLog()
        guardrail = _make_guardrail(audit=audit)
        auth = _make_auth(org_id="acme", team_id="eng")
        await guardrail.pre_call("tool", {"a": 1}, auth=auth)
        entries = await audit.get_entries()
        assert entries[0].org_id == "acme"
        assert entries[0].team_id == "eng"

    async def test_no_audit_log_does_not_crash(self) -> None:
        guardrail = _make_guardrail(audit=None)
        result = await guardrail.pre_call("tool", {"x": 1})
        assert result == {"x": 1}


class TestPostCallFiltersPII:
    """post_call filters PII from results."""

    async def test_api_key_redacted(self) -> None:
        guardrail = _make_guardrail()
        result = await guardrail.post_call(
            "web_search",
            "Found key AKIAIOSFODNN7EXAMPLE in config",
        )
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED:" in result

    async def test_ip_address_redacted(self) -> None:
        guardrail = _make_guardrail()
        result = await guardrail.post_call(
            "web_search",
            "Server running at 10.10.21.40 on port 8080",
        )
        assert "10.10.21.40" not in result
        assert "[REDACTED:ip_address]" in result

    async def test_clean_result_unchanged(self) -> None:
        guardrail = _make_guardrail()
        result = await guardrail.post_call(
            "web_search",
            "Python is a great programming language",
        )
        assert result == "Python is a great programming language"


class TestPostCallOptimizesTokens:
    """post_call optimizes long token results."""

    async def test_long_result_truncated(self) -> None:
        guardrail = _make_guardrail()
        long_result = "x" * 10000
        result = await guardrail.post_call("web_search", long_result)
        assert len(result) < len(long_result)
        assert "truncated" in result.lower()

    async def test_short_result_not_truncated(self) -> None:
        guardrail = _make_guardrail()
        short_result = "Hello world"
        result = await guardrail.post_call("web_search", short_result)
        assert result == short_result


class TestPostCallAudit:
    """post_call creates audit log entries."""

    async def test_audit_entry_created_on_post_call(self) -> None:
        audit = InMemoryAuditLog()
        guardrail = _make_guardrail(audit=audit)
        await guardrail.post_call(
            "web_search",
            "clean result",
            auth=_make_auth(),
        )
        entries = await audit.get_entries()
        assert len(entries) == 1
        assert entries[0].boundary == "post_call"
        assert entries[0].tool_name == "web_search"

    async def test_pii_flagged_in_audit(self) -> None:
        audit = InMemoryAuditLog()
        guardrail = _make_guardrail(audit=audit)
        await guardrail.post_call(
            "web_search",
            "Key: AKIAIOSFODNN7EXAMPLE",
            auth=_make_auth(),
        )
        entries = await audit.get_entries()
        assert entries[0].verdict == "flagged"
        assert any("pii_detected" in v.rule for v in entries[0].violations)

    async def test_clean_result_verdict_clean(self) -> None:
        audit = InMemoryAuditLog()
        guardrail = _make_guardrail(audit=audit)
        await guardrail.post_call(
            "web_search",
            "safe result",
            auth=_make_auth(),
        )
        entries = await audit.get_entries()
        assert entries[0].verdict == "clean"
