"""Tests for cost analytics and chargeback reporting.

Covers:
- Recording cost records and summarizing by org
- Group-by user/team/model/task_type
- Period filtering
- CSV export format
- Optimization suggestions (detects expensive model for simple tasks)
- Org-scoped isolation
- API routes require admin auth
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.analytics.costs import CostRecord, CostSummary, InMemoryCostTracker
from stronghold.api.routes.analytics import router as analytics_router
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
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
from tests.fakes import FakeAuthProvider, FakeLLMClient


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tracker() -> InMemoryCostTracker:
    return InMemoryCostTracker()


def _record(
    *,
    user_id: str = "user-1",
    org_id: str = "org-a",
    team_id: str = "team-x",
    model: str = "gpt-4",
    provider: str = "openai",
    task_type: str = "chat",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cost_usd: float = 0.01,
    timestamp: float = 0.0,
) -> CostRecord:
    return CostRecord(
        user_id=user_id,
        org_id=org_id,
        team_id=team_id,
        model=model,
        provider=provider,
        task_type=task_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        timestamp=timestamp,
    )


# ── Unit tests: InMemoryCostTracker ──────────────────────────────────


class TestCostRecordStorage:
    """Test basic record and summary."""

    async def test_record_stores_entry(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record())
        summary = await tracker.get_summary(org_id="org-a")
        assert summary.total_requests == 1
        assert summary.total_cost_usd == pytest.approx(0.01)

    async def test_record_accumulates(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(cost_usd=0.05, input_tokens=200, output_tokens=100))
        await tracker.record(_record(cost_usd=0.03, input_tokens=150, output_tokens=75))
        summary = await tracker.get_summary(org_id="org-a")
        assert summary.total_requests == 2
        assert summary.total_cost_usd == pytest.approx(0.08)
        assert summary.total_tokens == 525  # 200+100+150+75


class TestGroupBy:
    """Test group_by user/team/model/task_type."""

    async def test_group_by_user(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(user_id="alice", cost_usd=0.10))
        await tracker.record(_record(user_id="alice", cost_usd=0.05))
        await tracker.record(_record(user_id="bob", cost_usd=0.20))
        summary = await tracker.get_summary(org_id="org-a", group_by="user")
        assert summary.by_user["alice"] == pytest.approx(0.15)
        assert summary.by_user["bob"] == pytest.approx(0.20)

    async def test_group_by_team(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(team_id="frontend", cost_usd=0.10))
        await tracker.record(_record(team_id="backend", cost_usd=0.25))
        summary = await tracker.get_summary(org_id="org-a", group_by="team")
        assert summary.by_team["frontend"] == pytest.approx(0.10)
        assert summary.by_team["backend"] == pytest.approx(0.25)

    async def test_group_by_model(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(model="gpt-4", cost_usd=0.30))
        await tracker.record(_record(model="gpt-3.5-turbo", cost_usd=0.01))
        summary = await tracker.get_summary(org_id="org-a", group_by="model")
        assert summary.by_model["gpt-4"] == pytest.approx(0.30)
        assert summary.by_model["gpt-3.5-turbo"] == pytest.approx(0.01)

    async def test_group_by_task_type(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(task_type="chat", cost_usd=0.05))
        await tracker.record(_record(task_type="code", cost_usd=0.50))
        await tracker.record(_record(task_type="code", cost_usd=0.30))
        summary = await tracker.get_summary(org_id="org-a", group_by="task_type")
        assert summary.by_task_type["chat"] == pytest.approx(0.05)
        assert summary.by_task_type["code"] == pytest.approx(0.80)

    async def test_summary_always_populates_all_groups(
        self, tracker: InMemoryCostTracker
    ) -> None:
        """Even when group_by is 'user', all breakdown dicts are populated."""
        await tracker.record(
            _record(user_id="u1", team_id="t1", model="m1", task_type="chat", cost_usd=0.10)
        )
        summary = await tracker.get_summary(org_id="org-a", group_by="user")
        assert "u1" in summary.by_user
        assert "t1" in summary.by_team
        assert "m1" in summary.by_model
        assert "chat" in summary.by_task_type


class TestPeriodFiltering:
    """Test period-based filtering."""

    async def test_period_filter_includes_matching(self, tracker: InMemoryCostTracker) -> None:
        # Use month-based periods: "2026-03"
        await tracker.record(_record(timestamp=1743465600.0, cost_usd=0.10))  # 2025-04-01
        await tracker.record(_record(timestamp=1748736000.0, cost_usd=0.20))  # 2025-06-01
        summary = await tracker.get_summary(org_id="org-a", period="2025-04")
        assert summary.total_requests == 1
        assert summary.total_cost_usd == pytest.approx(0.10)

    async def test_no_period_returns_all(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(timestamp=1743465600.0, cost_usd=0.10))
        await tracker.record(_record(timestamp=1748736000.0, cost_usd=0.20))
        summary = await tracker.get_summary(org_id="org-a")
        assert summary.total_requests == 2
        assert summary.total_cost_usd == pytest.approx(0.30)


class TestOrgScoping:
    """Test org_id scoping — records from other orgs are invisible."""

    async def test_org_isolation(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(org_id="org-a", cost_usd=0.10))
        await tracker.record(_record(org_id="org-b", cost_usd=0.50))
        summary_a = await tracker.get_summary(org_id="org-a")
        summary_b = await tracker.get_summary(org_id="org-b")
        assert summary_a.total_cost_usd == pytest.approx(0.10)
        assert summary_b.total_cost_usd == pytest.approx(0.50)
        assert summary_a.total_requests == 1
        assert summary_b.total_requests == 1


class TestCSVExport:
    """Test CSV export format."""

    async def test_csv_has_header_and_rows(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(user_id="alice", model="gpt-4", cost_usd=0.10))
        await tracker.record(_record(user_id="bob", model="gpt-3.5-turbo", cost_usd=0.02))
        csv_str = await tracker.export_csv(org_id="org-a")
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 2
        assert "user_id" in reader.fieldnames
        assert "cost_usd" in reader.fieldnames
        assert "model" in reader.fieldnames

    async def test_csv_org_scoped(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(org_id="org-a", cost_usd=0.10))
        await tracker.record(_record(org_id="org-b", cost_usd=0.50))
        csv_str = await tracker.export_csv(org_id="org-a")
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 1

    async def test_csv_period_filtered(self, tracker: InMemoryCostTracker) -> None:
        await tracker.record(_record(timestamp=1743465600.0, cost_usd=0.10))  # 2025-04
        await tracker.record(_record(timestamp=1748736000.0, cost_usd=0.20))  # 2025-06
        csv_str = await tracker.export_csv(org_id="org-a", period="2025-04")
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 1


class TestOptimizationSuggestions:
    """Test cost optimization suggestions."""

    async def test_suggests_cheaper_model(self, tracker: InMemoryCostTracker) -> None:
        """Detects when an expensive model is used for simple tasks that a cheaper model also handles."""
        # Expensive model used for chat
        for _ in range(10):
            await tracker.record(
                _record(model="gpt-4", task_type="chat", cost_usd=0.30, input_tokens=100)
            )
        # Cheap model also used for chat
        for _ in range(5):
            await tracker.record(
                _record(model="gpt-3.5-turbo", task_type="chat", cost_usd=0.01, input_tokens=100)
            )

        suggestions = await tracker.get_optimization_suggestions(org_id="org-a")
        assert len(suggestions) >= 1
        # At least one suggestion should mention the expensive model or cost difference
        texts = [s.get("message", "") for s in suggestions]
        assert any("gpt-4" in t or "expensive" in t.lower() for t in texts)

    async def test_no_suggestions_for_single_model(self, tracker: InMemoryCostTracker) -> None:
        """No cheaper alternative if only one model is used for a task type."""
        await tracker.record(_record(model="gpt-4", task_type="code", cost_usd=0.30))
        suggestions = await tracker.get_optimization_suggestions(org_id="org-a")
        # Should either be empty or not suggest cheaper models for code
        cost_suggestions = [s for s in suggestions if s.get("type") == "cheaper_model"]
        assert len(cost_suggestions) == 0

    async def test_suggests_high_spend_task(self, tracker: InMemoryCostTracker) -> None:
        """Suggests caching or review when one task type dominates spend."""
        for _ in range(20):
            await tracker.record(_record(task_type="code", cost_usd=0.50))
        await tracker.record(_record(task_type="chat", cost_usd=0.01))
        suggestions = await tracker.get_optimization_suggestions(org_id="org-a")
        texts = [s.get("message", "") for s in suggestions]
        assert any("code" in t.lower() or "spend" in t.lower() for t in texts)


class TestCostSummaryDataclass:
    """Test CostSummary and CostRecord dataclass construction."""

    def test_cost_record_defaults(self) -> None:
        r = CostRecord()
        assert r.user_id == ""
        assert r.cost_usd == 0.0
        assert r.input_tokens == 0

    def test_cost_summary_defaults(self) -> None:
        s = CostSummary()
        assert s.total_cost_usd == 0.0
        assert s.total_tokens == 0
        assert s.by_user == {}

    def test_cost_summary_org_id(self) -> None:
        s = CostSummary(org_id="org-test", period="2025-03")
        assert s.org_id == "org-test"
        assert s.period == "2025-03"


# ── API route tests ──────────────────────────────────────────────────


@pytest.fixture
def analytics_app() -> FastAPI:
    """Create a FastAPI app with analytics routes and a pre-populated tracker."""
    app = FastAPI()
    app.include_router(analytics_router)

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
    audit_log = InMemoryAuditLog()
    cost_tracker = InMemoryCostTracker()

    async def setup() -> Container:
        # Seed some cost data — use __system__ org_id to match StaticKeyAuthProvider
        await cost_tracker.record(
            _record(
                user_id="alice", team_id="eng", model="gpt-4",
                cost_usd=0.30, org_id="__system__",
            )
        )
        await cost_tracker.record(
            _record(
                user_id="bob", team_id="ops", model="gpt-3.5-turbo",
                cost_usd=0.02, org_id="__system__",
            )
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            cost_tracker=cost_tracker,
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestAnalyticsCostsRoute:
    """Test GET /v1/stronghold/analytics/costs."""

    def test_returns_summary(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get(
                "/v1/stronghold/analytics/costs",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_requests"] == 2
            assert data["total_cost_usd"] == pytest.approx(0.32)

    def test_requires_auth(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get("/v1/stronghold/analytics/costs")
            assert resp.status_code == 401

    def test_requires_admin(self, analytics_app: FastAPI) -> None:
        analytics_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(analytics_app) as client:
            resp = client.get(
                "/v1/stronghold/analytics/costs",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 403

    def test_group_by_param(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get(
                "/v1/stronghold/analytics/costs?group_by=model",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "gpt-4" in data["by_model"]


class TestAnalyticsExportRoute:
    """Test GET /v1/stronghold/analytics/costs/export."""

    def test_returns_csv(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get(
                "/v1/stronghold/analytics/costs/export",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
            reader = csv.DictReader(io.StringIO(resp.text))
            rows = list(reader)
            assert len(rows) == 2

    def test_requires_auth(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get("/v1/stronghold/analytics/costs/export")
            assert resp.status_code == 401


class TestAnalyticsSuggestionsRoute:
    """Test GET /v1/stronghold/analytics/suggestions."""

    def test_returns_suggestions(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get(
                "/v1/stronghold/analytics/suggestions",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)

    def test_requires_auth(self, analytics_app: FastAPI) -> None:
        with TestClient(analytics_app) as client:
            resp = client.get("/v1/stronghold/analytics/suggestions")
            assert resp.status_code == 401
