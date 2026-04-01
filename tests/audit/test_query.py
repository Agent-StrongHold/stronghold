"""Tests for audit log query engine and API routes."""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.api.routes.audit import router as audit_router
from stronghold.audit.query import AuditQueryEngine
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
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from stronghold.types.security import AuditEntry
from tests.fakes import FakeAuthProvider, FakeLLMClient


def _make_entry(
    *,
    boundary: str = "warden",
    user_id: str = "user-1",
    org_id: str = "__system__",
    verdict: str = "allowed",
    agent_id: str = "arbiter",
    tool_name: str | None = None,
    timestamp: datetime | None = None,
    detail: str = "",
) -> AuditEntry:
    """Build an AuditEntry with defaults."""
    return AuditEntry(
        timestamp=timestamp or datetime.now(UTC),
        boundary=boundary,
        user_id=user_id,
        org_id=org_id,
        verdict=verdict,
        agent_id=agent_id,
        tool_name=tool_name,
        detail=detail,
    )


async def _seed_audit_log(audit_log: InMemoryAuditLog) -> None:
    """Populate audit log with diverse test entries."""
    now = datetime.now(UTC)
    entries = [
        _make_entry(
            boundary="warden",
            user_id="alice",
            verdict="allowed",
            timestamp=now - timedelta(hours=3),
        ),
        _make_entry(
            boundary="sentinel",
            user_id="alice",
            verdict="blocked",
            timestamp=now - timedelta(hours=2),
        ),
        _make_entry(
            boundary="warden",
            user_id="bob",
            verdict="allowed",
            tool_name="ha_control",
            timestamp=now - timedelta(hours=1),
        ),
        _make_entry(
            boundary="gate",
            user_id="bob",
            verdict="allowed",
            timestamp=now - timedelta(minutes=30),
        ),
        _make_entry(
            boundary="warden",
            user_id="alice",
            verdict="allowed",
            timestamp=now - timedelta(minutes=10),
        ),
        _make_entry(
            boundary="sentinel",
            user_id="charlie",
            verdict="blocked",
            timestamp=now - timedelta(minutes=5),
        ),
    ]
    for entry in entries:
        await audit_log.log(entry)


# ── Unit tests for AuditQueryEngine ────────────────────────────────


class TestAuditQueryEngine:
    """Unit tests for AuditQueryEngine filtering and aggregation."""

    def test_query_returns_all_entries(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        entries = loop.run_until_complete(engine.query(limit=100))
        assert len(entries) == 6

    def test_query_filters_by_user_id(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        entries = loop.run_until_complete(engine.query(user_id="alice", limit=100))
        assert len(entries) == 3
        assert all(e.user_id == "alice" for e in entries)

    def test_query_filters_by_boundary(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        entries = loop.run_until_complete(engine.query(boundary="sentinel", limit=100))
        assert len(entries) == 2
        assert all(e.boundary == "sentinel" for e in entries)

    def test_query_filters_by_since(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        cutoff = datetime.now(UTC) - timedelta(minutes=35)
        entries = loop.run_until_complete(engine.query(since=cutoff, limit=100))
        # Should only include entries from last 35 minutes (gate, warden, sentinel)
        assert len(entries) == 3

    def test_query_respects_limit(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        entries = loop.run_until_complete(engine.query(limit=2))
        assert len(entries) == 2

    def test_stats_aggregation(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        stats = loop.run_until_complete(engine.stats())
        assert stats["total"] == 6
        assert stats["per_boundary"]["warden"] == 3
        assert stats["per_boundary"]["sentinel"] == 2
        assert stats["per_boundary"]["gate"] == 1
        assert stats["per_user"]["alice"] == 3
        assert stats["per_user"]["bob"] == 2
        assert stats["per_user"]["charlie"] == 1
        assert stats["per_verdict"]["allowed"] == 4
        assert stats["per_verdict"]["blocked"] == 2
        # per_hour should have at least one key
        assert len(stats["per_hour"]) >= 1

    def test_export_csv_format(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        csv_data = loop.run_until_complete(engine.export_csv())
        reader = csv.reader(io.StringIO(csv_data))
        rows = list(reader)
        # Header + 6 data rows
        assert len(rows) == 7
        header = rows[0]
        assert header[0] == "timestamp"
        assert header[1] == "boundary"
        assert header[2] == "user_id"
        assert "verdict" in header

    def test_export_csv_filters(self) -> None:
        audit_log = InMemoryAuditLog()
        engine = AuditQueryEngine(audit_log)
        loop = asyncio.get_event_loop()
        loop.run_until_complete(_seed_audit_log(audit_log))
        csv_data = loop.run_until_complete(
            engine.export_csv(user_id="bob")
        )
        reader = csv.reader(io.StringIO(csv_data))
        rows = list(reader)
        # Header + 2 bob entries
        assert len(rows) == 3


# ── API route tests ────────────────────────────────────────────────


@pytest.fixture
def audit_app() -> FastAPI:
    """Create a FastAPI app with audit routes and pre-populated entries."""
    app = FastAPI()
    app.include_router(audit_router)

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

    audit_log = InMemoryAuditLog()
    warden = Warden()

    async def setup() -> Container:
        await _seed_audit_log(audit_log)
        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=InMemoryPromptManager(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestAuditQueryRoute:
    """Tests for GET /v1/stronghold/audit."""

    def test_returns_entries(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 6

    def test_filters_by_boundary(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit?boundary=sentinel",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert all(e["boundary"] == "sentinel" for e in data)

    def test_filters_by_user_id(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit?user_id=bob",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            assert all(e["user_id"] == "bob" for e in data)

    def test_respects_limit(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit?limit=3",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 3

    def test_rejects_unauthenticated(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get("/v1/stronghold/audit")
            assert resp.status_code == 401

    def test_rejects_non_admin(self, audit_app: FastAPI) -> None:
        audit_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 403

    def test_invalid_since_returns_400(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit?since=not-a-date",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 400
            assert "Invalid" in resp.json()["detail"]


class TestAuditExportRoute:
    """Tests for GET /v1/stronghold/audit/export."""

    def test_returns_csv(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit/export",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            assert resp.headers["content-type"] == "text/csv; charset=utf-8"
            assert "attachment" in resp.headers.get("content-disposition", "")
            reader = csv.reader(io.StringIO(resp.text))
            rows = list(reader)
            assert len(rows) == 7  # header + 6 entries

    def test_csv_filters_by_user(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit/export?user_id=charlie",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            reader = csv.reader(io.StringIO(resp.text))
            rows = list(reader)
            assert len(rows) == 2  # header + 1 charlie entry

    def test_rejects_unauthenticated(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get("/v1/stronghold/audit/export")
            assert resp.status_code == 401


class TestAuditStatsRoute:
    """Tests for GET /v1/stronghold/audit/stats."""

    def test_returns_stats(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get(
                "/v1/stronghold/audit/stats",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 6
            assert data["per_boundary"]["warden"] == 3
            assert data["per_boundary"]["sentinel"] == 2
            assert data["per_user"]["alice"] == 3
            assert data["per_verdict"]["allowed"] == 4
            assert "per_hour" in data

    def test_rejects_unauthenticated(self, audit_app: FastAPI) -> None:
        with TestClient(audit_app) as client:
            resp = client.get("/v1/stronghold/audit/stats")
            assert resp.status_code == 401
