"""Comprehensive tests for the Conduit pipeline (conduit.py).

Tests the full route_request flow: classify -> route -> quota check ->
sufficiency -> agent dispatch -> response format.  Covers session stickiness,
data-sharing consent, ambiguity routing to arbiter, quota exhaustion, intent
hints, creative-always-clarify, fallback agents, and response structure.

Uses only fakes and factories from tests/fakes.py and tests/factories.py.
No unittest.mock.
"""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.classifier.engine import ClassifierEngine
from stronghold.conduit import Conduit
from stronghold.container import Container
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from stronghold.types.errors import QuotaExhaustedError
from tests.factories import build_auth_context
from tests.fakes import FakeLLMClient, FakeQuotaTracker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(text: str) -> list[dict[str, Any]]:
    """Build a minimal user message list."""
    return [{"role": "user", "content": text}]


def _make_llm() -> FakeLLMClient:
    """Create a FakeLLMClient with a default response."""
    llm = FakeLLMClient()
    llm.set_simple_response("Agent response content")
    return llm


def _build_container(
    *,
    agents: dict[str, Agent] | None = None,
    intent_table: dict[str, str] | None = None,
    task_types: dict[str, TaskTypeConfig] | None = None,
    providers: dict[str, dict[str, object]] | None = None,
    models: dict[str, dict[str, object]] | None = None,
    llm: FakeLLMClient | None = None,
    quota_tracker: InMemoryQuotaTracker | FakeQuotaTracker | None = None,
) -> Container:
    """Build a minimal Container with sensible defaults for Conduit tests."""
    llm = llm or _make_llm()
    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()
    qt = quota_tracker or InMemoryQuotaTracker()

    _task_types = task_types or {
        "chat": TaskTypeConfig(
            keywords=["hello", "hi", "hey", "thanks"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "code": TaskTypeConfig(
            keywords=["code", "function", "bug", "error", "implement"],
            min_tier="medium",
            preferred_strengths=["code"],
        ),
        "automation": TaskTypeConfig(
            keywords=["light", "fan", "turn on", "turn off"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "search": TaskTypeConfig(
            keywords=["search", "look up", "find"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
    }

    _providers = providers or {
        "test_provider": {
            "status": "active",
            "billing_cycle": "monthly",
            "free_tokens": 1_000_000_000,
        },
    }

    _models = models or {
        "test-medium": {
            "provider": "test_provider",
            "litellm_id": "test/medium",
            "tier": "medium",
            "quality": 0.6,
            "speed": 500,
            "strengths": ["code", "chat", "reasoning"],
        },
    }

    config = StrongholdConfig(
        providers=_providers,
        models=_models,
        task_types=_task_types,
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    def _agent(name: str) -> Agent:
        return Agent(
            identity=AgentIdentity(
                name=name,
                soul_prompt_name=f"agent.{name}.soul",
                model="test/medium",
                memory_config={"learnings": True},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
            learning_store=learning_store,
        )

    _agents = agents or {
        "arbiter": _agent("arbiter"),
        "artificer": _agent("artificer"),
        "ranger": _agent("ranger"),
        "scribe": _agent("scribe"),
        "warden-at-arms": _agent("warden-at-arms"),
    }

    _intent_table = intent_table or {
        "code": "artificer",
        "search": "ranger",
        "creative": "scribe",
        "automation": "warden-at-arms",
    }

    perm_table = PermissionTable.from_config({"admin": ["*"]})

    container = Container(
        config=config,
        auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
        permission_table=perm_table,
        router=RouterEngine(qt),
        classifier=ClassifierEngine(),
        quota_tracker=qt,
        prompt_manager=prompts,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=InMemorySessionStore(),
        audit_log=InMemoryAuditLog(),
        warden=warden,
        gate=Gate(warden=warden),
        sentinel=Sentinel(
            warden=warden,
            permission_table=perm_table,
            audit_log=InMemoryAuditLog(),
        ),
        tracer=NoopTracingBackend(),  # type: ignore[arg-type]
        context_builder=context_builder,
        intent_registry=IntentRegistry(_intent_table),
        llm=llm,  # type: ignore[arg-type]
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        agents=_agents,
    )
    return container


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestConduitBasicRouting:
    """Tests for the basic classify -> route -> dispatch flow."""

    async def test_chat_message_routes_to_arbiter(self) -> None:
        """A plain 'hello' message classifies as chat and falls back to arbiter."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(_make_messages("hello"), auth=auth)

        assert result["object"] == "chat.completion"
        assert result["choices"][0]["message"]["role"] == "assistant"
        assert result["choices"][0]["finish_reason"] == "stop"
        # chat has no mapping in the intent table, so falls back to arbiter
        assert result["_routing"]["agent"] == "arbiter"

    async def test_code_request_routes_to_artificer(self) -> None:
        """A code-heavy request routes to the artificer agent."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages(
                "write a function in utils.py that sorts a list of integers. "
                "Return the sorted list. Include type hints."
            ),
            auth=auth,
        )

        assert result["_routing"]["agent"] == "artificer"
        assert result["_routing"]["intent"]["task_type"] == "code"

    async def test_automation_request_routes_to_warden_at_arms(self) -> None:
        """Automation request routes to warden-at-arms."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("turn on the bedroom light"),
            auth=auth,
        )

        assert result["_routing"]["agent"] == "warden-at-arms"
        assert result["_routing"]["intent"]["task_type"] == "automation"

    async def test_search_request_routes_to_ranger(self) -> None:
        """Search request routes to ranger."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("search for the latest Kubernetes release notes"),
            auth=auth,
        )

        assert result["_routing"]["agent"] == "ranger"
        assert result["_routing"]["intent"]["task_type"] == "search"


class TestConduitResponseFormat:
    """Tests for OpenAI-compatible response structure."""

    async def test_response_has_openai_structure(self) -> None:
        """Successful response has id, object, model, choices, usage, _routing."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("hello there"),
            auth=auth,
        )

        assert "id" in result
        assert result["object"] == "chat.completion"
        assert "model" in result
        assert len(result["choices"]) == 1
        assert result["choices"][0]["index"] == 0
        assert result["choices"][0]["message"]["role"] == "assistant"
        assert "content" in result["choices"][0]["message"]
        assert result["choices"][0]["finish_reason"] == "stop"
        assert "usage" in result
        assert "_routing" in result

    async def test_response_includes_usage_for_normal_dispatch(self) -> None:
        """Normal agent dispatch includes prompt/completion/total token counts."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("hello there"),
            auth=auth,
        )

        usage = result["usage"]
        assert "prompt_tokens" in usage
        assert "completion_tokens" in usage
        assert "total_tokens" in usage

    async def test_routing_metadata_has_intent_and_model(self) -> None:
        """The _routing dict carries intent details and selected model."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        # Use a fully detailed code message that passes sufficiency analysis
        result = await conduit.route_request(
            _make_messages(
                "write a function in auth.py to parse JSON web tokens. "
                "Return the claims dict. Include tests. Python FastAPI."
            ),
            auth=auth,
        )

        routing = result["_routing"]
        assert "intent" in routing
        assert "task_type" in routing["intent"]
        assert "agent" in routing
        assert "model" in routing


class TestConduitAuthValidation:
    """Tests for auth requirement enforcement."""

    async def test_none_auth_raises_type_error(self) -> None:
        """route_request with auth=None raises TypeError."""
        container = _build_container()
        conduit = Conduit(container)

        with pytest.raises(TypeError, match="AuthContext"):
            await conduit.route_request(_make_messages("hello"), auth=None)

    async def test_wrong_type_auth_raises_type_error(self) -> None:
        """route_request with a non-AuthContext raises TypeError."""
        container = _build_container()
        conduit = Conduit(container)

        with pytest.raises(TypeError, match="AuthContext"):
            await conduit.route_request(
                _make_messages("hello"),
                auth="not-an-auth",
            )


class TestConduitIntentHint:
    """Tests for the intent_hint bypass of classification."""

    async def test_intent_hint_bypasses_classifier(self) -> None:
        """Supplying intent_hint skips keyword/LLM classification."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        # "hello" would classify as chat, force automation via hint.
        # Use automation because it has low sufficiency bar (3 words, just what+where).
        result = await conduit.route_request(
            _make_messages("turn on the bedroom light"),
            auth=auth,
            intent_hint="automation",
        )

        assert result["_routing"]["intent"]["task_type"] == "automation"
        assert result["_routing"]["intent"]["classified_by"] == "hint"
        assert result["_routing"]["agent"] == "warden-at-arms"

    async def test_unknown_intent_hint_falls_through_to_classifier(self) -> None:
        """An intent_hint not in task_types is ignored; classifier runs."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("hello"),
            auth=auth,
            intent_hint="nonexistent_type",
        )

        # Falls through to classifier, which picks chat for "hello"
        assert result["_routing"]["intent"]["classified_by"] != "hint"


class TestConduitSessionStickiness:
    """Tests for session -> agent stickiness."""

    async def test_session_sticky_to_agent(self) -> None:
        """After routing to artificer, same session re-routes there."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()
        session_id = "sticky-session-1"

        # First request: code message with full sufficiency signals
        # (what=write/function, where=auth.py/module, how=return/tests, context=python)
        r1 = await conduit.route_request(
            _make_messages(
                "write a function in auth.py to validate JWT tokens. "
                "Return True if valid. Include tests. Python FastAPI."
            ),
            auth=auth,
            session_id=session_id,
        )
        assert r1["_routing"]["agent"] == "artificer"

        # Second request: ambiguous text, but session sticks to artificer
        r2 = await conduit.route_request(
            _make_messages("now refactor that please"),
            auth=auth,
            session_id=session_id,
        )
        assert r2["_routing"]["agent"] == "artificer"

    async def test_different_sessions_are_independent(self) -> None:
        """Two different session IDs don't share stickiness."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        # Session A -> artificer (fully detailed to pass sufficiency)
        await conduit.route_request(
            _make_messages(
                "write a function in auth.py to validate JWT tokens. "
                "Return True if valid. Include tests. Python FastAPI."
            ),
            auth=auth,
            session_id="session-a",
        )

        # Session B -> not sticky, routes by classification
        r2 = await conduit.route_request(
            _make_messages("hello there"),
            auth=auth,
            session_id="session-b",
        )
        # "hello there" classifies as chat, falls back to arbiter
        assert r2["_routing"]["agent"] == "arbiter"

    async def test_session_stickiness_eviction(self) -> None:
        """When sticky session map exceeds max, old entries are evicted."""
        container = _build_container()
        conduit = Conduit(container)
        conduit._MAX_STICKY_SESSIONS = 3  # small cap for testing
        auth = build_auth_context()

        # Use a fully detailed code message that passes sufficiency.
        # Eviction in step 8 only runs for non-arbiter agents AFTER
        # sufficiency passes.
        msg = (
            "write a function in auth.py to validate JWT tokens. "
            "Return True if valid. Include tests. Python FastAPI."
        )

        # Fill up sticky sessions
        for i in range(5):
            await conduit.route_request(
                _make_messages(msg),
                auth=auth,
                session_id=f"evict-session-{i}",
            )

        # Eviction fires when len > MAX; oldest entries are removed
        assert len(conduit._session_agents) <= 3


class TestConduitQuota:
    """Tests for quota pre-check."""

    async def test_quota_exhausted_raises_error(self) -> None:
        """When all providers are at 100%+ usage, raise QuotaExhaustedError."""
        qt = FakeQuotaTracker(usage_pct=1.0)
        container = _build_container(quota_tracker=qt)
        conduit = Conduit(container)
        auth = build_auth_context()

        with pytest.raises(QuotaExhaustedError):
            await conduit.route_request(_make_messages("hello"), auth=auth)

    async def test_quota_available_succeeds(self) -> None:
        """When provider has quota available, request succeeds."""
        qt = FakeQuotaTracker(usage_pct=0.5)
        container = _build_container(quota_tracker=qt)
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(_make_messages("hello"), auth=auth)
        assert result["object"] == "chat.completion"

    async def test_paygo_provider_bypasses_quota_check(self) -> None:
        """A provider with overage pricing is always available."""
        qt = FakeQuotaTracker(usage_pct=1.5)  # over 100%
        container = _build_container(
            providers={
                "paygo_provider": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 100,
                    "overage_cost_per_1k_input": 0.01,
                    "overage_cost_per_1k_output": 0.03,
                },
            },
            models={
                "paygo-model": {
                    "provider": "paygo_provider",
                    "litellm_id": "paygo/model",
                    "tier": "medium",
                    "quality": 0.6,
                    "speed": 500,
                    "strengths": ["code", "chat"],
                },
            },
            quota_tracker=qt,
        )
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(_make_messages("hello"), auth=auth)
        assert result["object"] == "chat.completion"


class TestConduitAmbiguity:
    """Tests for ambiguous request routing to arbiter."""

    async def test_ambiguous_request_routes_to_arbiter(self) -> None:
        """When keyword scores are ambiguous, route to arbiter for clarification."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        # "find error" scores on both search ("find") and code ("error")
        # both at 1.0 each, below the 3.0 threshold -> ambiguous
        result = await conduit.route_request(
            _make_messages("find error"),
            auth=auth,
        )

        assert result["id"] == "stronghold-clarify"
        routing = result["_routing"]
        assert routing["intent"]["classified_by"] == "ambiguous"
        assert routing["agent"] == "arbiter"

    async def test_intent_hint_skips_ambiguity_check(self) -> None:
        """When intent_hint is given, ambiguity check is skipped."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("find error"),
            auth=auth,
            intent_hint="code",
        )

        # Should NOT be a clarification response
        assert result["id"] != "stronghold-clarify"
        assert result["_routing"]["intent"]["task_type"] == "code"


class TestConduitDataSharingConsent:
    """Tests for data-sharing consent flow."""

    async def test_data_sharing_consent_prompt(self) -> None:
        """Provider with data_sharing=True triggers consent prompt."""
        qt = FakeQuotaTracker(usage_pct=0.0)
        container = _build_container(
            providers={
                "private_provider": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 1_000_000,
                },
                "sharing_provider": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 1_000_000,
                    "data_sharing": True,
                    "data_sharing_notice": "This provider shares your data.",
                },
            },
            models={
                "private-model": {
                    "provider": "private_provider",
                    "litellm_id": "private/model",
                    "tier": "small",
                    "quality": 0.3,
                    "speed": 200,
                    "strengths": ["chat"],
                },
                "sharing-model": {
                    "provider": "sharing_provider",
                    "litellm_id": "sharing/model",
                    "tier": "medium",
                    "quality": 0.9,
                    "speed": 1000,
                    "strengths": ["chat", "code", "reasoning"],
                },
            },
            quota_tracker=qt,
        )
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("hello there friend"),
            auth=auth,
            session_id="consent-session",
        )

        # Should trigger consent prompt because the data-sharing provider
        # scores higher but hasn't been consented to
        assert result["id"] == "stronghold-consent-required"
        assert "sharing_provider" in result["_routing"].get("provider", "")

    async def test_consent_affirmative_unlocks_provider(self) -> None:
        """After user says 'yes', the data-sharing provider is consented."""
        qt = FakeQuotaTracker(usage_pct=0.0)
        container = _build_container(
            providers={
                "private_provider": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 1_000_000,
                },
                "sharing_provider": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 1_000_000,
                    "data_sharing": True,
                    "data_sharing_notice": "This provider shares your data.",
                },
            },
            models={
                "private-model": {
                    "provider": "private_provider",
                    "litellm_id": "private/model",
                    "tier": "small",
                    "quality": 0.3,
                    "speed": 200,
                    "strengths": ["chat"],
                },
                "sharing-model": {
                    "provider": "sharing_provider",
                    "litellm_id": "sharing/model",
                    "tier": "medium",
                    "quality": 0.9,
                    "speed": 1000,
                    "strengths": ["chat", "code", "reasoning"],
                },
            },
            quota_tracker=qt,
        )
        conduit = Conduit(container)
        auth = build_auth_context()
        sid = "consent-flow-session"

        # Step 1: trigger consent prompt
        await conduit.route_request(
            _make_messages("hello there friend"),
            auth=auth,
            session_id=sid,
        )

        # Step 2: user affirms consent
        r2 = await conduit.route_request(
            _make_messages("yes"),
            auth=auth,
            session_id=sid,
        )

        # The provider should now be consented
        assert "sharing_provider" in conduit._session_consents.get(sid, set())
        # Response should be a normal completion, not another consent prompt
        assert r2["id"] != "stronghold-consent-required"


class TestConduitSufficiency:
    """Tests for the sufficiency analysis (needs-detail) flow."""

    async def test_creative_always_asks_for_detail(self) -> None:
        """Creative task type always triggers 'needs_detail' on first request."""
        container = _build_container(
            task_types={
                "chat": TaskTypeConfig(
                    keywords=["hello", "hi"],
                    preferred_strengths=["chat"],
                ),
                "creative": TaskTypeConfig(
                    keywords=["write a story", "write a poem", "creative writing"],
                    min_tier="medium",
                    preferred_strengths=["creative"],
                ),
            },
            intent_table={"creative": "scribe"},
        )
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("write a story about dragons"),
            auth=auth,
            session_id="creative-session",
        )

        assert result["id"] == "stronghold-needs-detail"
        assert result["_routing"]["intent"]["classified_by"] == "needs_detail"
        assert "missing" in result["_routing"]

    async def test_sufficiency_sets_stickiness_for_followup(self) -> None:
        """After a needs_detail response, the session sticks to the target agent."""
        container = _build_container(
            task_types={
                "chat": TaskTypeConfig(
                    keywords=["hello", "hi"],
                    preferred_strengths=["chat"],
                ),
                "creative": TaskTypeConfig(
                    keywords=["write a story", "write a poem", "creative writing"],
                    min_tier="medium",
                    preferred_strengths=["creative"],
                ),
            },
            intent_table={"creative": "scribe"},
        )
        conduit = Conduit(container)
        auth = build_auth_context()
        sid = "suff-sticky-session"

        # First request triggers needs_detail
        await conduit.route_request(
            _make_messages("write a story about dragons"),
            auth=auth,
            session_id=sid,
        )

        # Session should be sticky to scribe
        assert conduit._session_agents.get(sid) == "scribe"


class TestConduitFallbackAgent:
    """Tests for fallback when no agent matches."""

    async def test_no_matching_agent_falls_back_to_arbiter(self) -> None:
        """When intent registry returns None and no sticky, use arbiter."""
        container = _build_container(
            intent_table={},  # no mappings
        )
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("hello there"),
            auth=auth,
        )

        assert result["_routing"]["agent"] == "arbiter"

    async def test_fallback_when_arbiter_missing(self) -> None:
        """When arbiter is not registered, falls back to any available agent."""
        llm = _make_llm()
        warden = Warden()
        prompts = InMemoryPromptManager()
        cb = ContextBuilder()
        ls = InMemoryLearningStore()

        only_agent = Agent(
            identity=AgentIdentity(
                name="lonely",
                soul_prompt_name="agent.lonely.soul",
                model="test/medium",
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=cb,
            prompt_manager=prompts,
            warden=warden,
            learning_store=ls,
        )

        container = _build_container(
            agents={"lonely": only_agent},
            intent_table={},
            llm=llm,
        )
        conduit = Conduit(container)
        auth = build_auth_context()

        result = await conduit.route_request(
            _make_messages("hello"),
            auth=auth,
        )

        # With no arbiter and no intent mapping, lonely should be used
        assert result["_routing"]["agent"] == "lonely"


class TestConduitTokenEstimate:
    """Tests for the static _estimate_tokens helper."""

    def test_estimate_simple_text(self) -> None:
        """Simple text is estimated at ~chars/4, min 1."""
        estimate = Conduit._estimate_tokens([{"content": "Hello world"}])
        # "Hello world" = 11 chars -> 11 // 4 = 2
        assert estimate >= 1

    def test_estimate_empty_messages(self) -> None:
        """Empty message list returns 1 (the minimum)."""
        estimate = Conduit._estimate_tokens([])
        assert estimate == 1

    def test_estimate_multimodal_content(self) -> None:
        """Multimodal messages (list content) extract text parts."""
        msgs = [
            {
                "content": [
                    {"type": "text", "text": "Look at this image"},
                    {"type": "image_url", "image_url": {"url": "data:..."}},
                ],
            }
        ]
        estimate = Conduit._estimate_tokens(msgs)
        assert estimate >= 1

    def test_estimate_missing_content(self) -> None:
        """Messages without 'content' key contribute 0 chars."""
        estimate = Conduit._estimate_tokens([{"role": "system"}])
        assert estimate == 1


class TestConduitBuildResponse:
    """Tests for the _build_response static method."""

    def test_build_response_with_usage(self) -> None:
        """include_usage=True adds populated usage dict."""
        resp = Conduit._build_response(
            response_id="test-123",
            model="test/model",
            content="Hello",
            routing={"agent": "arbiter"},
            include_usage=True,
        )
        assert resp["usage"]["prompt_tokens"] == 0
        assert resp["usage"]["completion_tokens"] == 0
        assert resp["usage"]["total_tokens"] == 0

    def test_build_response_without_usage(self) -> None:
        """include_usage=False returns empty usage dict."""
        resp = Conduit._build_response(
            response_id="test-456",
            model="test/model",
            content="Hello",
            routing={"agent": "arbiter"},
            include_usage=False,
        )
        assert resp["usage"] == {}


class TestConduitStatusCallback:
    """Tests for the status_callback integration."""

    async def test_status_callback_invoked(self) -> None:
        """status_callback receives status messages during routing."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()
        statuses: list[str] = []

        async def on_status(msg: str) -> None:
            statuses.append(msg)

        await conduit.route_request(
            _make_messages("hello"),
            auth=auth,
            status_callback=on_status,
        )

        assert len(statuses) >= 2  # at least "Classifying intent..." and "working..."
        assert any("Classifying" in s for s in statuses)


class TestConduitEdgeCases:
    """Tests for edge cases and boundary conditions."""

    async def test_inactive_provider_ignored_in_quota_check(self) -> None:
        """Inactive providers are skipped during quota pre-check."""
        qt = FakeQuotaTracker(usage_pct=0.0)
        container = _build_container(
            providers={
                "active_one": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 1_000_000,
                },
                "dead_one": {
                    "status": "inactive",
                    "billing_cycle": "monthly",
                    "free_tokens": 0,
                },
            },
            models={
                "active-model": {
                    "provider": "active_one",
                    "litellm_id": "active/model",
                    "tier": "medium",
                    "quality": 0.6,
                    "speed": 500,
                    "strengths": ["chat", "code"],
                },
            },
            quota_tracker=qt,
        )
        conduit = Conduit(container)
        auth = build_auth_context()

        # Should succeed because the active provider has quota
        result = await conduit.route_request(
            _make_messages("hello"),
            auth=auth,
        )
        assert result["object"] == "chat.completion"

    async def test_no_session_id_skips_stickiness(self) -> None:
        """Without a session_id, no stickiness tracking happens."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        await conduit.route_request(
            _make_messages("write a function to compute fibonacci. Include type hints."),
            auth=auth,
            session_id=None,
        )

        assert len(conduit._session_agents) == 0

    async def test_agent_dispatch_error_propagates(self) -> None:
        """When agent.handle raises, conduit re-raises the exception."""
        container = _build_container()
        conduit = Conduit(container)
        auth = build_auth_context()

        # Replace the arbiter agent with one that raises
        original_handle = container.agents["arbiter"].handle

        async def broken_handle(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Agent exploded")

        container.agents["arbiter"].handle = broken_handle  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="Agent exploded"):
            await conduit.route_request(
                _make_messages("hello"),
                auth=auth,
            )

        # Restore
        container.agents["arbiter"].handle = original_handle  # type: ignore[method-assign]
