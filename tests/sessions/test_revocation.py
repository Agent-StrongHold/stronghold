"""Tests for session revocation: revoke, revoke_user, is_revoked, API routes."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.sessions import router as sessions_router
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
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeLLMClient


# ── Unit tests: InMemorySessionStore revocation ────────────────────────


class TestRevokeSession:
    """Test revoking a single session."""

    async def test_revoke_existing_returns_true(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        result = await store.revoke("org1/t/u:s1", org_id="org1")
        assert result is True

    async def test_revoke_nonexistent_returns_false(self) -> None:
        store = InMemorySessionStore()
        result = await store.revoke("org1/t/u:no-such", org_id="org1")
        assert result is False

    async def test_revoke_wrong_org_returns_false(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        result = await store.revoke("org1/t/u:s1", org_id="org2")
        assert result is False

    async def test_revoked_session_returns_empty_history(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        await store.revoke("org1/t/u:s1", org_id="org1")
        history = await store.get_history("org1/t/u:s1")
        assert history == []

    async def test_revoke_idempotent(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        await store.revoke("org1/t/u:s1", org_id="org1")
        # Second revoke should still return True (session exists in revoked set)
        result = await store.revoke("org1/t/u:s1", org_id="org1")
        assert result is True


class TestIsRevoked:
    """Test checking revocation status."""

    async def test_not_revoked_returns_false(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        assert await store.is_revoked("org1/t/u:s1", org_id="org1") is False

    async def test_revoked_returns_true(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        await store.revoke("org1/t/u:s1", org_id="org1")
        assert await store.is_revoked("org1/t/u:s1", org_id="org1") is True

    async def test_wrong_org_returns_false(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("org1/t/u:s1", [{"role": "user", "content": "hi"}])
        await store.revoke("org1/t/u:s1", org_id="org1")
        # Wrong org should not see the revocation
        assert await store.is_revoked("org1/t/u:s1", org_id="org2") is False

    async def test_nonexistent_returns_false(self) -> None:
        store = InMemorySessionStore()
        assert await store.is_revoked("org1/t/u:nope", org_id="org1") is False


class TestRevokeUser:
    """Test bulk revocation by user_id."""

    async def test_revoke_all_user_sessions(self) -> None:
        store = InMemorySessionStore()
        # Two sessions for user "alice" in org1
        await store.append_messages(
            "org1/team1/alice:s1", [{"role": "user", "content": "a"}]
        )
        await store.append_messages(
            "org1/team1/alice:s2", [{"role": "user", "content": "b"}]
        )
        # One session for user "bob" in org1
        await store.append_messages(
            "org1/team1/bob:s3", [{"role": "user", "content": "c"}]
        )
        count = await store.revoke_user("alice", org_id="org1")
        assert count == 2

        # Alice's sessions are revoked
        assert await store.is_revoked("org1/team1/alice:s1", org_id="org1") is True
        assert await store.is_revoked("org1/team1/alice:s2", org_id="org1") is True
        # Bob's session is not
        assert await store.is_revoked("org1/team1/bob:s3", org_id="org1") is False

    async def test_revoke_user_wrong_org_returns_zero(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "org1/team1/alice:s1", [{"role": "user", "content": "a"}]
        )
        count = await store.revoke_user("alice", org_id="org2")
        assert count == 0

    async def test_revoke_user_no_sessions_returns_zero(self) -> None:
        store = InMemorySessionStore()
        count = await store.revoke_user("nobody", org_id="org1")
        assert count == 0

    async def test_revoked_user_sessions_return_empty_history(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "org1/team1/alice:s1", [{"role": "user", "content": "a"}]
        )
        await store.revoke_user("alice", org_id="org1")
        history = await store.get_history("org1/team1/alice:s1")
        assert history == []


# ── API route tests ────────────────────────────────────────────────────


API_KEY = "sk-test-key-stronghold-minimum-32chars"
AUTH_HEADER = {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture
def revocation_app() -> FastAPI:
    """Create a FastAPI app with sessions routes and pre-populated sessions."""
    app = FastAPI()
    app.include_router(sessions_router)

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
        router_api_key=API_KEY,
    )

    prompts = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    warden = Warden()
    context_builder = ContextBuilder()
    session_store = InMemorySessionStore()
    audit_log = InMemoryAuditLog()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        # Pre-populate sessions for __system__ org
        for sid in [
            "__system__/_/alice:session1",
            "__system__/_/alice:session2",
            "__system__/_/bob:session3",
        ]:
            await session_store.append_messages(
                sid, [{"role": "user", "content": f"hello from {sid}"}]
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
            learning_store=learning_store,
        )

        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key=API_KEY),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=learning_store,
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=session_store,
            audit_log=audit_log,
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=InMemoryAuditLog(),
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


class TestRevokeSessionRoute:
    """DELETE /v1/stronghold/sessions/revoke/{session_id} — admin only."""

    def test_revoke_returns_200(self, revocation_app: FastAPI) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke/__system__/_/alice:session1",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "revoked"
            assert data["session_id"] == "__system__/_/alice:session1"

    def test_revoke_nonexistent_returns_404(self, revocation_app: FastAPI) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke/__system__/_/nobody:nosession",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 404

    def test_revoke_unauthenticated_returns_401(self, revocation_app: FastAPI) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke/__system__/_/alice:session1",
            )
            assert resp.status_code == 401

    def test_revoked_session_history_empty(self, revocation_app: FastAPI) -> None:
        with TestClient(revocation_app) as client:
            # Revoke
            client.post(
                "/v1/stronghold/sessions/revoke/__system__/_/alice:session1",
                headers=AUTH_HEADER,
            )
            # Get history — should be empty
            resp = client.get(
                "/v1/stronghold/sessions/__system__/_/alice:session1",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            assert resp.json()["messages"] == []


class TestRevokeUserRoute:
    """POST /v1/stronghold/sessions/revoke-user?user_id=... — admin only."""

    def test_revoke_user_returns_200_with_count(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke-user?user_id=alice",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "revoked"
            assert data["revoked_count"] == 2

    def test_revoke_user_no_sessions_returns_200_zero(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke-user?user_id=nobody",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["revoked_count"] == 0

    def test_revoke_user_missing_param_returns_422(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke-user",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 422

    def test_revoke_user_unauthenticated_returns_401(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            resp = client.post(
                "/v1/stronghold/sessions/revoke-user?user_id=alice",
            )
            assert resp.status_code == 401

    def test_revoked_user_sessions_return_empty_history(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            # Revoke all alice sessions
            client.post(
                "/v1/stronghold/sessions/revoke-user?user_id=alice",
                headers=AUTH_HEADER,
            )
            # Both alice sessions should return empty
            for sid in ["__system__/_/alice:session1", "__system__/_/alice:session2"]:
                resp = client.get(
                    f"/v1/stronghold/sessions/{sid}",
                    headers=AUTH_HEADER,
                )
                assert resp.status_code == 200
                assert resp.json()["messages"] == []

            # Bob's session should still have data
            resp = client.get(
                "/v1/stronghold/sessions/__system__/_/bob:session3",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            assert len(resp.json()["messages"]) == 1


class TestRevocationAudit:
    """Revocation should create audit log entries."""

    def test_revoke_session_creates_audit_entry(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            client.post(
                "/v1/stronghold/sessions/revoke/__system__/_/alice:session1",
                headers=AUTH_HEADER,
            )
            # Check audit log via container
            container = revocation_app.state.container
            audit_log = container.audit_log

            loop = asyncio.get_event_loop()
            entries = loop.run_until_complete(
                audit_log.get_entries(org_id="__system__")
            )
            revoke_entries = [
                e for e in entries if e.boundary == "session_revocation"
            ]
            assert len(revoke_entries) >= 1
            assert revoke_entries[0].detail == "__system__/_/alice:session1"

    def test_revoke_user_creates_audit_entry(
        self, revocation_app: FastAPI
    ) -> None:
        with TestClient(revocation_app) as client:
            client.post(
                "/v1/stronghold/sessions/revoke-user?user_id=alice",
                headers=AUTH_HEADER,
            )
            container = revocation_app.state.container
            audit_log = container.audit_log

            loop = asyncio.get_event_loop()
            entries = loop.run_until_complete(
                audit_log.get_entries(org_id="__system__")
            )
            revoke_entries = [
                e for e in entries if e.boundary == "session_revocation_bulk"
            ]
            assert len(revoke_entries) >= 1
            assert "alice" in revoke_entries[0].detail
