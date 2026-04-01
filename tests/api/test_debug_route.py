"""Tests for the debug route-explain endpoint.

POST /v1/stronghold/debug/route-explain
Dry-run classification + routing without dispatching to an agent.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.debug import router as debug_router
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
from stronghold.types.auth import PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeAuthProvider, FakeLLMClient


@pytest.fixture
def debug_app() -> FastAPI:
    """Create a FastAPI app with the debug route and a real container."""
    app = FastAPI()
    app.include_router(debug_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")

    config = StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000000},
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
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug"],
                min_tier="medium",
                preferred_strengths=["code"],
            ),
        },
        permissions={"admin": ["*"], "user": ["web_search"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        default_agent = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
        )

        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=InMemoryLearningStore(),
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
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestDebugRouteExplain:
    """Tests for POST /v1/stronghold/debug/route-explain."""

    def test_returns_200_with_explanation(self, debug_app: FastAPI) -> None:
        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "Write a function to sort a list"}],
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "intent" in data
            assert "explanation" in data
            assert "candidates" in data
            assert "decision" in data

    def test_returns_intent_details(self, debug_app: FastAPI) -> None:
        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "Write a function to sort a list"}],
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            data = resp.json()
            intent = data["intent"]
            assert "task_type" in intent
            assert "complexity" in intent
            assert "classified_by" in intent

    def test_intent_hint_overrides_classification(self, debug_app: FastAPI) -> None:
        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "intent_hint": "code",
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            data = resp.json()
            assert data["intent"]["task_type"] == "code"

    def test_requires_admin_auth_401(self, debug_app: FastAPI) -> None:
        """Missing auth header returns 401."""
        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            assert resp.status_code == 401

    def test_requires_admin_role_403(self, debug_app: FastAPI) -> None:
        """Non-admin user gets 403."""
        # Reconfigure auth to return a non-admin user
        container = debug_app.state.container
        from stronghold.types.auth import AuthContext

        non_admin = AuthContext(
            user_id="user1",
            username="regular",
            roles=frozenset({"user"}),
            auth_method="api_key",
        )

        container.auth_provider = FakeAuthProvider(auth_context=non_admin)  # type: ignore[assignment]

        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers={"Authorization": "Bearer fake-token"},
            )
            assert resp.status_code == 403

    def test_explanation_is_nonempty_string(self, debug_app: FastAPI) -> None:
        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "Fix the bug in my code"}],
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            data = resp.json()
            assert isinstance(data["explanation"], str)
            assert len(data["explanation"]) > 0

    def test_candidates_have_scores(self, debug_app: FastAPI) -> None:
        with TestClient(debug_app) as client:
            resp = client.post(
                "/v1/stronghold/debug/route-explain",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            data = resp.json()
            for cand in data["candidates"]:
                assert "model" in cand
                assert "score" in cand
