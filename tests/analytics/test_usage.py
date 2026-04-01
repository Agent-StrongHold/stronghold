"""Tests for per-user usage tracking and reporting.

Covers:
- Recording usage events
- Aggregation (get_summary)
- Period filtering
- by_task_type aggregation
- by_model aggregation
- org_id scoping
- API routes (/usage/me, /usage/summary)
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.analytics.usage import InMemoryUsageTracker, UsageRecord, UsageSummary
from stronghold.types.auth import AuthContext
from tests.fakes import FakeAuthProvider


# ── InMemoryUsageTracker Unit Tests ─────────────────────────────────


class TestUsageRecord:
    def test_defaults(self) -> None:
        r = UsageRecord()
        assert r.user_id == ""
        assert r.org_id == ""
        assert r.model == ""
        assert r.provider == ""
        assert r.task_type == ""
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.timestamp == 0.0

    def test_custom_values(self) -> None:
        r = UsageRecord(
            user_id="alice",
            org_id="org-1",
            model="gpt-4",
            provider="openai",
            task_type="code",
            input_tokens=100,
            output_tokens=200,
            timestamp=1000.0,
        )
        assert r.user_id == "alice"
        assert r.input_tokens == 100
        assert r.output_tokens == 200


class TestUsageSummary:
    def test_defaults(self) -> None:
        s = UsageSummary()
        assert s.user_id == ""
        assert s.total_input_tokens == 0
        assert s.total_output_tokens == 0
        assert s.total_requests == 0
        assert s.by_task_type == {}
        assert s.by_model == {}


class TestRecordUsage:
    async def test_record_stores_event(self) -> None:
        tracker = InMemoryUsageTracker()
        record = UsageRecord(user_id="alice", org_id="org-1", input_tokens=50)
        await tracker.record(record)
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.total_requests == 1
        assert summary.total_input_tokens == 50

    async def test_record_multiple_events(self) -> None:
        tracker = InMemoryUsageTracker()
        for i in range(5):
            await tracker.record(
                UsageRecord(user_id="alice", org_id="org-1", input_tokens=10, output_tokens=20)
            )
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.total_requests == 5
        assert summary.total_input_tokens == 50
        assert summary.total_output_tokens == 100


class TestGetSummary:
    async def test_empty_tracker_returns_zeros(self) -> None:
        tracker = InMemoryUsageTracker()
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.total_requests == 0
        assert summary.total_input_tokens == 0
        assert summary.total_output_tokens == 0
        assert summary.by_task_type == {}
        assert summary.by_model == {}

    async def test_summary_user_id_and_org_id(self) -> None:
        tracker = InMemoryUsageTracker()
        await tracker.record(UsageRecord(user_id="alice", org_id="org-1", input_tokens=10))
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.user_id == "alice"
        assert summary.org_id == "org-1"


class TestPeriodFiltering:
    async def test_matches_period(self) -> None:
        tracker = InMemoryUsageTracker()
        # March 2026
        march_ts = 1774934400.0  # 2026-03-28 ~UTC
        # April 2026
        april_ts = 1775625600.0  # 2026-04-06 ~UTC

        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1", input_tokens=100, timestamp=march_ts,
            )
        )
        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1", input_tokens=200, timestamp=april_ts,
            )
        )

        march_summary = await tracker.get_summary(
            user_id="alice", org_id="org-1", period="2026-03",
        )
        assert march_summary.total_requests == 1
        assert march_summary.total_input_tokens == 100
        assert march_summary.period == "2026-03"

        april_summary = await tracker.get_summary(
            user_id="alice", org_id="org-1", period="2026-04",
        )
        assert april_summary.total_requests == 1
        assert april_summary.total_input_tokens == 200

    async def test_empty_period_returns_all(self) -> None:
        tracker = InMemoryUsageTracker()
        await tracker.record(
            UsageRecord(user_id="alice", org_id="org-1", input_tokens=50, timestamp=1000.0)
        )
        await tracker.record(
            UsageRecord(user_id="alice", org_id="org-1", input_tokens=50, timestamp=2000000000.0)
        )
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.total_requests == 2
        assert summary.total_input_tokens == 100


class TestByTaskTypeAggregation:
    async def test_aggregates_by_task_type(self) -> None:
        tracker = InMemoryUsageTracker()
        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1",
                task_type="code", input_tokens=100, output_tokens=50,
            )
        )
        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1",
                task_type="chat", input_tokens=30, output_tokens=20,
            )
        )
        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1",
                task_type="code", input_tokens=60, output_tokens=40,
            )
        )
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.by_task_type["code"] == 250  # 100+50+60+40
        assert summary.by_task_type["chat"] == 50  # 30+20


class TestByModelAggregation:
    async def test_aggregates_by_model(self) -> None:
        tracker = InMemoryUsageTracker()
        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1",
                model="gpt-4", input_tokens=100, output_tokens=50,
            )
        )
        await tracker.record(
            UsageRecord(
                user_id="alice", org_id="org-1",
                model="claude-3", input_tokens=200, output_tokens=100,
            )
        )
        summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary.by_model["gpt-4"] == 150
        assert summary.by_model["claude-3"] == 300


class TestOrgIdScoping:
    async def test_different_org_ids_isolated(self) -> None:
        tracker = InMemoryUsageTracker()
        await tracker.record(
            UsageRecord(user_id="alice", org_id="org-1", input_tokens=100)
        )
        await tracker.record(
            UsageRecord(user_id="alice", org_id="org-2", input_tokens=200)
        )
        summary_1 = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert summary_1.total_input_tokens == 100
        assert summary_1.total_requests == 1

        summary_2 = await tracker.get_summary(user_id="alice", org_id="org-2")
        assert summary_2.total_input_tokens == 200
        assert summary_2.total_requests == 1

    async def test_different_users_same_org_isolated(self) -> None:
        tracker = InMemoryUsageTracker()
        await tracker.record(
            UsageRecord(user_id="alice", org_id="org-1", input_tokens=100)
        )
        await tracker.record(
            UsageRecord(user_id="bob", org_id="org-1", input_tokens=200)
        )
        alice_summary = await tracker.get_summary(user_id="alice", org_id="org-1")
        assert alice_summary.total_input_tokens == 100

        bob_summary = await tracker.get_summary(user_id="bob", org_id="org-1")
        assert bob_summary.total_input_tokens == 200


# ── API Route Tests ─────────────────────────────────────────────────

# Minimal container for route testing
class _Container:
    def __init__(
        self,
        *,
        auth_provider: Any = None,
        usage_tracker: Any = None,
    ) -> None:
        self.auth_provider = auth_provider or FakeAuthProvider()
        self.usage_tracker = usage_tracker or InMemoryUsageTracker()


AUTH = {"Authorization": "Bearer sk-test"}


def _make_app(
    *,
    auth_provider: Any = None,
    usage_tracker: Any = None,
) -> FastAPI:
    from stronghold.api.routes.usage import router

    app = FastAPI()
    app.include_router(router)
    app.state.container = _Container(
        auth_provider=auth_provider,
        usage_tracker=usage_tracker or InMemoryUsageTracker(),
    )
    return app


class TestUsageMeRoute:
    def test_returns_200_for_authenticated_user(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/me", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_requests"] == 0
            assert data["total_input_tokens"] == 0
            assert data["total_output_tokens"] == 0

    def test_requires_auth_401(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/me")
            assert resp.status_code == 401

    def test_returns_usage_for_user(self) -> None:
        tracker = InMemoryUsageTracker()
        # Pre-populate tracker with a usage record (direct append to avoid async in sync test)
        tracker._records.append(
            UsageRecord(
                user_id="system", org_id="__system__",
                model="gpt-4", task_type="code",
                input_tokens=500, output_tokens=200,
            )
        )
        app = _make_app(usage_tracker=tracker)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/me", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_requests"] == 1
            assert data["total_input_tokens"] == 500
            assert data["total_output_tokens"] == 200

    def test_period_query_param(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/me?period=2026-03", headers=AUTH)
            assert resp.status_code == 200
            assert resp.json()["period"] == "2026-03"


class TestUsageSummaryRoute:
    def test_requires_auth_401(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/summary")
            assert resp.status_code == 401

    def test_requires_admin_role_403(self) -> None:
        # User without admin role
        non_admin = AuthContext(
            user_id="user1",
            org_id="org-1",
            roles=frozenset({"user"}),
        )
        app = _make_app(auth_provider=FakeAuthProvider(auth_context=non_admin))
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/summary", headers=AUTH)
            assert resp.status_code == 403

    def test_admin_can_access(self) -> None:
        admin = AuthContext(
            user_id="admin1",
            org_id="org-1",
            roles=frozenset({"admin", "user"}),
        )
        app = _make_app(auth_provider=FakeAuthProvider(auth_context=admin))
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/usage/summary", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert "summaries" in data
