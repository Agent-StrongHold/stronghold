"""Tests for API admin routes: learnings, outcomes, audit, config reload."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.admin import router as admin_router
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
from stronghold.types.memory import Learning
from tests.fakes import FakeAuthProvider, FakeLLMClient


@pytest.fixture
def admin_app() -> FastAPI:
    """Create a FastAPI app with admin routes and pre-populated learnings."""
    app = FastAPI()
    app.include_router(admin_router)

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
    learning_store = InMemoryLearningStore()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        # Pre-populate learnings
        lr1 = Learning(
            category="tool_correction",
            trigger_keys=["fan", "bedroom"],
            learning="entity_id for the fan is fan.bedroom_lamp",
            tool_name="ha_control",
            org_id="__system__",
        )
        lr2 = Learning(
            category="general",
            trigger_keys=["light", "kitchen"],
            learning="Use light.kitchen_main for the kitchen light",
            tool_name="ha_control",
            org_id="__system__",
        )
        await learning_store.store(lr1)
        await learning_store.store(lr2)

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
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
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
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestListLearnings:
    def test_admin_returns_learnings(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/learnings",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2
            names = [lr["tool_name"] for lr in data]
            assert all(n == "ha_control" for n in names)

    def test_non_admin_returns_403(self, admin_app: FastAPI) -> None:
        admin_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/learnings",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get("/v1/stronghold/admin/learnings")
            assert resp.status_code == 401


class TestAddLearning:
    def test_admin_stores_and_returns_id(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/learnings",
                json={
                    "category": "entity_mapping",
                    "trigger_keys": ["thermostat"],
                    "learning": "Use climate.living_room for the thermostat",
                    "tool_name": "ha_control",
                },
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "id" in data
            assert data["status"] == "stored"


class TestGetOutcomes:
    def test_admin_returns_stats(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/outcomes",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data
            assert "succeeded" in data
            assert "rate" in data


class TestGetAuditLog:
    def test_admin_returns_entries(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/audit",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)


class TestGetQuota:
    def test_admin_returns_quota_with_providers(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "providers" in data
            assert "summary" in data
            assert isinstance(data["providers"], list)
            assert len(data["providers"]) == 1
            prov = data["providers"][0]
            assert prov["provider"] == "test"
            assert prov["status"] == "active"
            assert prov["free_tokens"] == 1000000
            assert prov["usage_pct"] == 0.0

    def test_admin_returns_summary_totals(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            s = resp.json()["summary"]
            assert s["total_providers"] == 1
            assert s["active_providers"] == 1
            assert s["exhausted_providers"] == 0
            assert s["total_budget"] == 1000000

    def test_quota_reflects_recorded_usage(self, admin_app: FastAPI) -> None:
        import asyncio

        tracker = admin_app.state.container.quota_tracker
        asyncio.get_event_loop().run_until_complete(
            tracker.record_usage("test", "monthly", 500, 300)
        )
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            prov = resp.json()["providers"][0]
            assert prov["total_tokens"] == 800
            assert prov["input_tokens"] == 500
            assert prov["output_tokens"] == 300
            assert prov["request_count"] == 1
            assert prov["usage_pct"] == 0.0008

    def test_non_admin_returns_403(self, admin_app: FastAPI) -> None:
        admin_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 403


class TestGetQuotaUsage:
    def test_admin_returns_empty_breakdown(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/usage?group_by=user_id&days=7",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["group_by"] == "user_id"
            assert data["days"] == 7
            assert isinstance(data["data"], list)

    def test_breakdown_with_recorded_outcomes(self, admin_app: FastAPI) -> None:
        import asyncio

        from stronghold.types.memory import Outcome

        store = admin_app.state.container.outcome_store
        asyncio.get_event_loop().run_until_complete(
            store.record(
                Outcome(
                    user_id="alice",
                    org_id="__system__",
                    model_used="test/model",
                    input_tokens=1000,
                    output_tokens=500,
                    success=True,
                )
            )
        )
        asyncio.get_event_loop().run_until_complete(
            store.record(
                Outcome(
                    user_id="bob",
                    org_id="__system__",
                    model_used="test/model",
                    input_tokens=2000,
                    output_tokens=800,
                    success=True,
                )
            )
        )
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/usage?group_by=user_id",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            rows = resp.json()["data"]
            assert len(rows) == 2
            # Sorted by total_tokens descending — bob first
            assert rows[0]["group"] == "bob"
            assert rows[0]["total_tokens"] == 2800
            assert rows[1]["group"] == "alice"
            assert rows[1]["total_tokens"] == 1500

    def test_invalid_group_by_returns_400(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/usage?group_by=hacker",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400

    def test_model_breakdown(self, admin_app: FastAPI) -> None:
        import asyncio

        from stronghold.types.memory import Outcome

        store = admin_app.state.container.outcome_store
        asyncio.get_event_loop().run_until_complete(
            store.record(
                Outcome(
                    user_id="alice",
                    org_id="__system__",
                    model_used="gpt-4",
                    input_tokens=5000,
                    output_tokens=1000,
                )
            )
        )
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/usage?group_by=model_used",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            rows = resp.json()["data"]
            models = [r["group"] for r in rows]
            assert "gpt-4" in models


class TestAnalyzeQuota:
    def test_empty_question_returns_400(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/quota/analyze",
                json={"question": ""},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400

    def test_analyst_returns_answer(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/quota/analyze",
                json={"question": "What providers are configured?"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "answer" in data
            assert "chart" in data


class TestGetQuotaTimeseries:
    def test_empty_timeseries(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/timeseries?days=7",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["days"] == 7
            assert isinstance(data["series"], list)

    def test_timeseries_with_data(self, admin_app: FastAPI) -> None:
        import asyncio

        from stronghold.types.memory import Outcome

        store = admin_app.state.container.outcome_store
        asyncio.get_event_loop().run_until_complete(
            store.record(
                Outcome(
                    user_id="alice",
                    org_id="__system__",
                    model_used="test/model",
                    input_tokens=3000,
                    output_tokens=1000,
                )
            )
        )
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/timeseries?days=7",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            series = resp.json()["series"]
            assert len(series) >= 1
            assert series[0]["total_tokens"] >= 4000
            assert "date" in series[0]

    def test_timeseries_grouped(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/timeseries?group_by=model_used&days=7",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["group_by"] == "model_used"

    def test_invalid_group_by_returns_400(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota/timeseries?group_by=hacker",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400


class TestQuotaBurnRate:
    def test_quota_includes_burn_rate_fields(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            prov = resp.json()["providers"][0]
            assert "daily_burn_rate" in prov
            assert "days_until_exhaustion" in prov
            assert "overage_cost" in prov

    def test_summary_includes_overage_cost(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/quota",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert "total_overage_cost" in resp.json()["summary"]


class _FakeCoinLedger:
    def __init__(self) -> None:
        self._rate = 40

    async def get_banking_rate(self) -> int:
        return self._rate

    async def set_banking_rate(self, rate: int) -> None:
        self._rate = rate


class TestCoinSettings:
    def test_get_coin_settings(self, admin_app: FastAPI) -> None:
        admin_app.state.container.coin_ledger = _FakeCoinLedger()
        with TestClient(admin_app) as client:
            resp = client.get(
                "/v1/stronghold/admin/coins/settings",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "banking_rate_pct" in data
            assert "daily_copper_allowance" in data

    def test_update_coin_settings(self, admin_app: FastAPI) -> None:
        admin_app.state.container.coin_ledger = _FakeCoinLedger()
        with TestClient(admin_app) as client:
            resp = client.put(
                "/v1/stronghold/admin/coins/settings",
                json={"banking_rate_pct": 50},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            assert resp.json()["banking_rate_pct"] == 50

    def test_update_coin_settings_invalid_rate(self, admin_app: FastAPI) -> None:
        admin_app.state.container.coin_ledger = _FakeCoinLedger()
        with TestClient(admin_app) as client:
            resp = client.put(
                "/v1/stronghold/admin/coins/settings",
                json={"banking_rate_pct": 200},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400

    def test_update_coin_settings_zero_rate(self, admin_app: FastAPI) -> None:
        admin_app.state.container.coin_ledger = _FakeCoinLedger()
        with TestClient(admin_app) as client:
            resp = client.put(
                "/v1/stronghold/admin/coins/settings",
                json={"banking_rate_pct": 0},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400


class TestAnalyzeQuotaExtended:
    def test_analyst_with_populated_data(self, admin_app: FastAPI) -> None:
        """Exercises the data_sections branches (by user/team/model/provider + timeseries)."""
        import asyncio

        from stronghold.types.memory import Outcome

        store = admin_app.state.container.outcome_store
        asyncio.get_event_loop().run_until_complete(
            store.record(
                Outcome(
                    user_id="alice",
                    org_id="__system__",
                    team_id="team-a",
                    model_used="gpt-4",
                    input_tokens=4000,
                    output_tokens=1000,
                    response_time_ms=200,
                    success=True,
                )
            )
        )
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/quota/analyze",
                json={"question": "Who used the most tokens?"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200

    def test_analyst_question_too_long(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/quota/analyze",
                json={"question": "x" * 1001},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 400

    def test_analyst_extracts_chart_config(self, admin_app: FastAPI) -> None:
        """Exercise the chart extraction branch (lines 1447-1459)."""
        fake_llm = admin_app.state.container.llm
        fake_llm.set_simple_response(
            'Here are the numbers.\n```chartjs\n{"type":"bar","data":{"labels":["a"],"datasets":[]}}\n```\nEnd.'
        )
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/quota/analyze",
                json={"question": "Show me a chart"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["chart"] is not None
            assert data["chart"]["type"] == "bar"

    def test_analyst_malformed_chart_config(self, admin_app: FastAPI) -> None:
        """Malformed chart JSON leaves chart as None (line 1458-1459)."""
        fake_llm = admin_app.state.container.llm
        fake_llm.set_simple_response("Answer\n```chartjs\n{bad json\n```")
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/quota/analyze",
                json={"question": "Show me a chart"},
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 200

    def test_analyst_llm_exception_returns_502(self, admin_app: FastAPI) -> None:
        """LLM exception during analysis returns 502 (lines 1437-1442)."""
        fake_llm = admin_app.state.container.llm
        original_complete = fake_llm.complete

        async def broken_complete(*args, **kwargs):
            raise RuntimeError("llm down")

        fake_llm.complete = broken_complete  # type: ignore[method-assign]
        try:
            with TestClient(admin_app) as client:
                resp = client.post(
                    "/v1/stronghold/admin/quota/analyze",
                    json={"question": "Anything?"},
                    headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
                )
                assert resp.status_code == 502
        finally:
            fake_llm.complete = original_complete  # type: ignore[method-assign]


class TestReloadConfig:
    def test_admin_returns_501(self, admin_app: FastAPI) -> None:
        with TestClient(admin_app) as client:
            resp = client.post(
                "/v1/stronghold/admin/reload",
                headers={"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"},
            )
            assert resp.status_code == 501
            data = resp.json()
            assert data["status"] == "reload_not_yet_implemented"
