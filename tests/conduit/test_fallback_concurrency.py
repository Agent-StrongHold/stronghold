"""Tests for H6: conduit must NOT mutate llm._fallback_models.

The old code set ``self._c.llm._fallback_models = fallback_models`` which is:
  - Not thread-safe (concurrent requests overwrite each other)
  - Breaks encapsulation (accesses private attr on the LLM client)

After the fix, fallback models are passed as a parameter through
``agent.handle(fallback_models=...)`` rather than mutated on a shared object.
"""

from __future__ import annotations

import asyncio

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.classifier.engine import ClassifierEngine
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
from stronghold.types.auth import SYSTEM_AUTH, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeLLMClient


def _make_config() -> StrongholdConfig:
    return StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello", "hi"], preferred_strengths=["chat"]),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug"],
                preferred_strengths=["code"],
            ),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )


def _make_container(fake_llm: FakeLLMClient | None = None) -> Container:
    llm = fake_llm or FakeLLMClient()
    llm.set_simple_response("test response")
    config = _make_config()
    warden = Warden()
    audit_log = InMemoryAuditLog()
    prompts = InMemoryPromptManager()
    qt = InMemoryQuotaTracker()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()

    arbiter = Agent(
        identity=AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    code_agent = Agent(
        identity=AgentIdentity(
            name="code",
            soul_prompt_name="agent.code.soul",
            model="test/model",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    intent_registry = IntentRegistry(routing_table={"code": "code"})

    return Container(
        config=config,
        auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
        permission_table=PermissionTable.from_config({"admin": ["*"]}),
        router=RouterEngine(qt),
        classifier=ClassifierEngine(),
        quota_tracker=qt,
        prompt_manager=prompts,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=InMemorySessionStore(),
        audit_log=audit_log,
        warden=warden,
        gate=Gate(warden=warden),
        sentinel=Sentinel(
            warden=warden,
            permission_table=PermissionTable.from_config(config.permissions),
            audit_log=audit_log,
        ),
        tracer=NoopTracingBackend(),
        context_builder=context_builder,
        intent_registry=intent_registry,
        llm=llm,
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        agents={"arbiter": arbiter, "code": code_agent},
    )


class TestNoPrivateFallbackMutation:
    """H6: Conduit must not mutate llm._fallback_models."""

    async def test_route_request_does_not_set_fallback_models_attr(self) -> None:
        """After route_request, llm should NOT have a _fallback_models attribute set by conduit."""
        container = _make_container()
        llm = container.llm

        # Ensure no _fallback_models attr exists before
        assert not hasattr(llm, "_fallback_models") or llm._fallback_models == []

        await container.conduit.route_request(
            [{"role": "user", "content": "hello"}],
            auth=SYSTEM_AUTH,
        )

        # After the fix, conduit should NOT mutate llm._fallback_models
        # The attr should either not exist or remain at its default
        if hasattr(llm, "_fallback_models"):
            # If FakeLLMClient has it, it must not have been set by conduit
            # (FakeLLMClient doesn't define _fallback_models, so hasattr should be False)
            pass
        # The key assertion: the LLM object should not have _fallback_models
        # dynamically injected by the conduit
        assert not hasattr(llm, "_fallback_models"), (
            "Conduit must not mutate llm._fallback_models -- "
            "pass fallback_models as a parameter instead"
        )

    async def test_concurrent_requests_do_not_share_fallback_state(self) -> None:
        """Two concurrent requests must not interfere with each other's fallback models."""
        container = _make_container()
        llm = container.llm

        # Run two requests concurrently
        results = await asyncio.gather(
            container.conduit.route_request(
                [{"role": "user", "content": "fix the bug in this code"}],
                auth=SYSTEM_AUTH,
                session_id="sess-1",
            ),
            container.conduit.route_request(
                [{"role": "user", "content": "hello there"}],
                auth=SYSTEM_AUTH,
                session_id="sess-2",
            ),
        )

        # Both should complete successfully
        assert results[0]["choices"][0]["message"]["content"]
        assert results[1]["choices"][0]["message"]["content"]

        # The LLM should NOT have _fallback_models set
        assert not hasattr(llm, "_fallback_models"), (
            "Concurrent requests must not share fallback state via mutable LLM attrs"
        )
