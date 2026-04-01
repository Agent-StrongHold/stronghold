"""Validate that every factory produces correct defaults and every fake satisfies its protocol."""

from __future__ import annotations

from typing import Any

from stronghold.protocols.auth import AuthProvider
from stronghold.protocols.llm import LLMClient
from stronghold.protocols.prompts import PromptManager
from stronghold.protocols.quota import QuotaTracker
from stronghold.protocols.rate_limit import RateLimiter
from stronghold.protocols.tracing import Span, Trace, TracingBackend
from stronghold.types.auth import SYSTEM_AUTH, AuthContext, PermissionTable
from stronghold.types.config import RoutingConfig
from stronghold.types.intent import Intent
from stronghold.types.memory import EpisodicMemory, Learning, MemoryScope, MemoryTier
from stronghold.types.model import ModelConfig, ProviderConfig

from .factories import (
    build_auth_context,
    build_episodic_memory,
    build_intent,
    build_learning,
    build_model_config,
    build_permission_table,
    build_provider_config,
    build_routing_config,
)
from .fakes import (
    FakeAuthProvider,
    FakeLLMClient,
    FakePromptManager,
    FakeQuotaTracker,
    FakeRateLimiter,
    NoopSpan,
    NoopTrace,
    NoopTracingBackend,
)

# ── Factory default-value tests ──────────────────────────────────────


class TestBuildIntent:
    def test_defaults(self) -> None:
        intent = build_intent()
        assert isinstance(intent, Intent)
        assert intent.task_type == "chat"
        assert intent.complexity == "simple"
        assert intent.priority == "normal"
        assert intent.min_tier == "small"
        assert intent.preferred_strengths == ("chat",)
        assert intent.classified_by == "keywords"
        assert intent.keyword_score == 3.0
        assert intent.user_text == "hello"

    def test_override(self) -> None:
        intent = build_intent(task_type="code", complexity="complex", keyword_score=8.0)
        assert intent.task_type == "code"
        assert intent.complexity == "complex"
        assert intent.keyword_score == 8.0
        # non-overridden fields keep defaults
        assert intent.priority == "normal"


class TestBuildModelConfig:
    def test_defaults(self) -> None:
        mc = build_model_config()
        assert isinstance(mc, ModelConfig)
        assert mc.provider == "test_provider"
        assert mc.litellm_id == "test/model"
        assert mc.tier == "medium"
        assert mc.quality == 0.6
        assert mc.speed == 500
        assert mc.modality == "text"
        assert mc.strengths == ("code",)

    def test_override(self) -> None:
        mc = build_model_config(tier="large", quality=0.95)
        assert mc.tier == "large"
        assert mc.quality == 0.95

    def test_unknown_keys_ignored(self) -> None:
        mc = build_model_config(nonexistent_field="should_be_dropped")
        assert isinstance(mc, ModelConfig)
        assert not hasattr(mc, "nonexistent_field")


class TestBuildProviderConfig:
    def test_defaults(self) -> None:
        pc = build_provider_config()
        assert isinstance(pc, ProviderConfig)
        assert pc.status == "active"
        assert pc.billing_cycle == "monthly"
        assert pc.free_tokens == 1_000_000_000

    def test_override(self) -> None:
        pc = build_provider_config(status="inactive", free_tokens=500)
        assert pc.status == "inactive"
        assert pc.free_tokens == 500

    def test_unknown_keys_ignored(self) -> None:
        pc = build_provider_config(made_up_key=42)
        assert isinstance(pc, ProviderConfig)


class TestBuildRoutingConfig:
    def test_defaults(self) -> None:
        rc = build_routing_config()
        assert isinstance(rc, RoutingConfig)
        assert rc.quality_weight == 0.6
        assert rc.cost_weight == 0.4
        assert rc.reserve_pct == 0.05

    def test_override(self) -> None:
        rc = build_routing_config(quality_weight=0.9, cost_weight=0.1)
        assert rc.quality_weight == 0.9
        assert rc.cost_weight == 0.1


class TestBuildAuthContext:
    def test_defaults(self) -> None:
        ac = build_auth_context()
        assert isinstance(ac, AuthContext)
        assert ac.user_id == "test-user"
        assert ac.username == "tester"
        assert ac.roles == frozenset({"admin", "user"})
        assert ac.auth_method == "api_key"

    def test_override(self) -> None:
        ac = build_auth_context(user_id="u-99", roles=frozenset({"viewer"}))
        assert ac.user_id == "u-99"
        assert ac.roles == frozenset({"viewer"})


class TestBuildLearning:
    def test_defaults(self) -> None:
        lr = build_learning()
        assert isinstance(lr, Learning)
        assert lr.category == "tool_correction"
        assert lr.trigger_keys == ["fan", "bedroom"]
        assert "entity_id" in lr.learning
        assert lr.tool_name == "ha_control"
        assert lr.agent_id == "warden-at-arms"
        assert lr.scope == MemoryScope.AGENT

    def test_override(self) -> None:
        lr = build_learning(category="preference", scope=MemoryScope.USER)
        assert lr.category == "preference"
        assert lr.scope == MemoryScope.USER


class TestBuildEpisodicMemory:
    def test_defaults(self) -> None:
        em = build_episodic_memory()
        assert isinstance(em, EpisodicMemory)
        assert em.memory_id == "test-memory-001"
        assert em.tier == MemoryTier.LESSON
        assert em.weight == 0.6
        assert em.agent_id == "warden-at-arms"
        assert em.scope == MemoryScope.AGENT
        assert em.source == "test"
        assert "Schema injection" in em.content

    def test_override(self) -> None:
        em = build_episodic_memory(tier=MemoryTier.REGRET, weight=0.9)
        assert em.tier == MemoryTier.REGRET
        assert em.weight == 0.9


class TestBuildPermissionTable:
    def test_defaults(self) -> None:
        pt = build_permission_table()
        assert isinstance(pt, PermissionTable)
        assert "*" in pt.roles["admin"]
        assert "web_search" in pt.roles["engineer"]
        assert "web_search" in pt.roles["viewer"]

    def test_check_admin_wildcard(self) -> None:
        pt = build_permission_table()
        assert pt.check(frozenset({"admin"}), "anything_at_all") is True

    def test_check_role_specific_tool(self) -> None:
        pt = build_permission_table()
        assert pt.check(frozenset({"viewer"}), "web_search") is True
        assert pt.check(frozenset({"viewer"}), "shell") is False


# ── Fake protocol-conformance tests ──────────────────────────────────


class TestFakeLLMClient:
    def test_isinstance_llm_protocol(self) -> None:
        assert isinstance(FakeLLMClient(), LLMClient)

    async def test_default_response(self) -> None:
        client = FakeLLMClient()
        resp = await client.complete([{"role": "user", "content": "hi"}], "gpt-4")
        assert resp["id"] == "chatcmpl-fake-default"
        choices: list[dict[str, Any]] = resp["choices"]
        assert choices[0]["message"]["content"] == "Default fake response"

    async def test_set_simple_response(self) -> None:
        client = FakeLLMClient()
        client.set_simple_response("hello world")
        resp = await client.complete([{"role": "user", "content": "x"}], "m")
        assert resp["choices"][0]["message"]["content"] == "hello world"

    async def test_set_responses_sequence(self) -> None:
        client = FakeLLMClient()
        r1: dict[str, Any] = {"id": "1", "choices": [{"message": {"content": "first"}}]}
        r2: dict[str, Any] = {"id": "2", "choices": [{"message": {"content": "second"}}]}
        client.set_responses(r1, r2)
        first = await client.complete([], "m")
        second = await client.complete([], "m")
        assert first["id"] == "1"
        assert second["id"] == "2"
        # third call falls back to default
        third = await client.complete([], "m")
        assert third["id"] == "chatcmpl-fake-default"

    async def test_calls_recorded(self) -> None:
        client = FakeLLMClient()
        msgs: list[dict[str, Any]] = [{"role": "user", "content": "test"}]
        await client.complete(msgs, "model-x")
        assert len(client.calls) == 1
        assert client.calls[0]["model"] == "model-x"
        assert client.calls[0]["messages"] is msgs

    async def test_stream_yields_chunks(self) -> None:
        client = FakeLLMClient()
        chunks: list[str] = []
        async for chunk in client.stream([], "m"):
            chunks.append(chunk)
        assert len(chunks) == 2
        assert "fake stream" in chunks[0]
        assert "[DONE]" in chunks[1]


class TestFakePromptManager:
    def test_isinstance_prompt_protocol(self) -> None:
        assert isinstance(FakePromptManager(), PromptManager)

    async def test_get_missing_returns_empty(self) -> None:
        pm = FakePromptManager()
        assert await pm.get("nonexistent") == ""

    async def test_seed_and_get(self) -> None:
        pm = FakePromptManager()
        pm.seed("greeting", "Hello {name}")
        assert await pm.get("greeting") == "Hello {name}"

    async def test_get_with_config(self) -> None:
        pm = FakePromptManager()
        pm.seed("sys", "You are helpful", {"temperature": 0.7})
        text, cfg = await pm.get_with_config("sys")
        assert text == "You are helpful"
        assert cfg == {"temperature": 0.7}

    async def test_upsert_and_retrieve(self) -> None:
        pm = FakePromptManager()
        await pm.upsert("new_prompt", "content here", config={"k": "v"})
        text, cfg = await pm.get_with_config("new_prompt")
        assert text == "content here"
        assert cfg == {"k": "v"}


class TestNoopTracing:
    def test_backend_isinstance_protocol(self) -> None:
        assert isinstance(NoopTracingBackend(), TracingBackend)

    def test_trace_isinstance_protocol(self) -> None:
        assert isinstance(NoopTrace(), Trace)

    def test_span_isinstance_protocol(self) -> None:
        assert isinstance(NoopSpan(), Span)

    def test_create_trace_returns_trace(self) -> None:
        backend = NoopTracingBackend()
        trace = backend.create_trace(user_id="u1", session_id="s1", name="test")
        assert isinstance(trace, NoopTrace)
        assert trace.trace_id == "noop-trace-id"

    def test_trace_span_returns_span(self) -> None:
        trace = NoopTrace()
        span = trace.span("my-span")
        assert isinstance(span, NoopSpan)

    def test_span_context_manager(self) -> None:
        span = NoopSpan()
        with span as s:
            assert s is span

    def test_span_chaining(self) -> None:
        span = NoopSpan()
        result = span.set_input({"x": 1}).set_output({"y": 2}).set_usage(10, 20, "gpt-4")
        assert result is span

    def test_trace_score_and_update_noop(self) -> None:
        trace = NoopTrace()
        # These should not raise
        trace.score("quality", 0.9, comment="good")
        trace.update({"key": "value"})
        trace.end()


class TestFakeQuotaTracker:
    def test_isinstance_quota_protocol(self) -> None:
        assert isinstance(FakeQuotaTracker(), QuotaTracker)

    async def test_record_usage(self) -> None:
        qt = FakeQuotaTracker()
        result = await qt.record_usage("openai", "monthly", 100, 200)
        assert result["provider"] == "openai"
        assert result["total_tokens"] == 300
        assert len(qt.recorded) == 1
        assert qt.recorded[0]["input_tokens"] == 100

    async def test_get_usage_pct_default(self) -> None:
        qt = FakeQuotaTracker()
        pct = await qt.get_usage_pct("p", "monthly", 1_000_000)
        assert pct == 0.0

    async def test_get_usage_pct_custom(self) -> None:
        qt = FakeQuotaTracker(usage_pct=0.75)
        pct = await qt.get_usage_pct("p", "monthly", 1_000_000)
        assert pct == 0.75

    async def test_get_all_usage_empty(self) -> None:
        qt = FakeQuotaTracker()
        assert await qt.get_all_usage() == []


class TestFakeRateLimiter:
    def test_isinstance_rate_limiter_protocol(self) -> None:
        assert isinstance(FakeRateLimiter(), RateLimiter)

    async def test_always_allow_by_default(self) -> None:
        rl = FakeRateLimiter()
        allowed, headers = await rl.check("user-1")
        assert allowed is True
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers

    async def test_deny_mode(self) -> None:
        rl = FakeRateLimiter(always_allow=False)
        allowed, _headers = await rl.check("user-1")
        assert allowed is False

    async def test_calls_recorded(self) -> None:
        rl = FakeRateLimiter()
        await rl.check("k1")
        await rl.check("k2")
        assert rl.calls == ["k1", "k2"]

    async def test_record_noop(self) -> None:
        rl = FakeRateLimiter()
        await rl.record("some-key")  # should not raise


class TestFakeAuthProvider:
    def test_isinstance_auth_protocol(self) -> None:
        assert isinstance(FakeAuthProvider(), AuthProvider)

    async def test_returns_system_auth_by_default(self) -> None:
        ap = FakeAuthProvider()
        ctx = await ap.authenticate("Bearer token-xxx")
        assert ctx is SYSTEM_AUTH
        assert ctx.user_id == "system"

    async def test_custom_auth_context(self) -> None:
        custom = build_auth_context(user_id="custom-user")
        ap = FakeAuthProvider(auth_context=custom)
        ctx = await ap.authenticate("Bearer abc")
        assert ctx.user_id == "custom-user"

    async def test_missing_auth_raises(self) -> None:
        ap = FakeAuthProvider()
        import pytest

        with pytest.raises(ValueError, match="Missing Authorization"):
            await ap.authenticate(None)
