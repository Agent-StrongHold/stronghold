"""Tests for escalation API routes."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.escalations import router as escalations_router
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.escalation.manager import Escalation, InMemoryEscalationManager
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
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeAuthProvider, FakeLLMClient


@pytest.fixture
def esc_app() -> FastAPI:
    """Create a FastAPI app with escalation routes and seeded data."""
    app = FastAPI()
    app.include_router(escalations_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")

    config = StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()
    escalation_manager = InMemoryEscalationManager()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        # Seed two escalations in org __system__
        await escalation_manager.escalate(
            Escalation(
                id="esc-seed-1",
                session_id="sess-1",
                agent_name="artificer",
                user_id="user-1",
                org_id="__system__",
                reason="max_rounds_exceeded",
            )
        )
        await escalation_manager.escalate(
            Escalation(
                id="esc-seed-2",
                session_id="sess-2",
                agent_name="ranger",
                user_id="user-2",
                org_id="__system__",
                reason="timeout",
            )
        )
        # One in a different org — should not be visible
        await escalation_manager.escalate(
            Escalation(
                id="esc-other-org",
                session_id="sess-3",
                agent_name="scribe",
                user_id="user-3",
                org_id="org-other",
                reason="warden_block",
            )
        )

        default_agent = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
                memory_config={"learnings": True},
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
            learning_store=InMemoryLearningStore(),
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
            escalation_manager=escalation_manager,
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


AUTH_HEADERS = {"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"}


class TestListEscalations:
    def test_admin_lists_pending_escalations(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.get("/v1/stronghold/escalations", headers=AUTH_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            # Only __system__ org escalations (2 seeded)
            assert len(data) == 2
            ids = {e["id"] for e in data}
            assert ids == {"esc-seed-1", "esc-seed-2"}

    def test_unauthenticated_returns_401(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.get("/v1/stronghold/escalations")
            assert resp.status_code == 401

    def test_non_admin_returns_403(self, esc_app: FastAPI) -> None:
        esc_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(esc_app) as client:
            resp = client.get(
                "/v1/stronghold/escalations",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 403


class TestGetEscalation:
    def test_admin_gets_escalation_details(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.get("/v1/stronghold/escalations/esc-seed-1", headers=AUTH_HEADERS)
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == "esc-seed-1"
            assert data["agent_name"] == "artificer"
            assert data["reason"] == "max_rounds_exceeded"
            assert data["status"] == "pending"

    def test_returns_404_for_missing(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.get("/v1/stronghold/escalations/nonexistent", headers=AUTH_HEADERS)
            assert resp.status_code == 404

    def test_returns_404_for_other_org(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.get("/v1/stronghold/escalations/esc-other-org", headers=AUTH_HEADERS)
            assert resp.status_code == 404


class TestRespondEscalation:
    def test_respond_updates_status(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.post(
                "/v1/stronghold/escalations/esc-seed-1/respond",
                json={"response": "Try restarting the pipeline"},
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "responded"

            # Verify it's now responded
            detail = client.get(
                "/v1/stronghold/escalations/esc-seed-1", headers=AUTH_HEADERS
            )
            assert detail.json()["status"] == "responded"
            assert detail.json()["response"] == "Try restarting the pipeline"

    def test_respond_requires_response_body(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.post(
                "/v1/stronghold/escalations/esc-seed-1/respond",
                json={},
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 400

    def test_respond_fails_for_already_resolved(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            # First respond succeeds
            client.post(
                "/v1/stronghold/escalations/esc-seed-1/respond",
                json={"response": "first"},
                headers=AUTH_HEADERS,
            )
            # Second respond fails
            resp = client.post(
                "/v1/stronghold/escalations/esc-seed-1/respond",
                json={"response": "second"},
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 404


class TestTakeoverEscalation:
    def test_takeover_updates_status(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.post(
                "/v1/stronghold/escalations/esc-seed-1/takeover",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "taken_over"

    def test_takeover_returns_404_for_missing(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.post(
                "/v1/stronghold/escalations/nonexistent/takeover",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 404


class TestDismissEscalation:
    def test_dismiss_updates_status(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            resp = client.post(
                "/v1/stronghold/escalations/esc-seed-1/dismiss",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "dismissed"

    def test_dismiss_returns_404_for_already_resolved(self, esc_app: FastAPI) -> None:
        with TestClient(esc_app) as client:
            client.post(
                "/v1/stronghold/escalations/esc-seed-1/dismiss",
                headers=AUTH_HEADERS,
            )
            resp = client.post(
                "/v1/stronghold/escalations/esc-seed-1/dismiss",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 404
