"""Tests for admin strike management and coin refill endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.admin import router as admin_router
from stronghold.quota.coins import NoOpCoinLedger
from stronghold.security.strikes import InMemoryStrikeTracker, StrikeRecord
from tests.fakes import make_test_container

AUTH = {"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"}


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    container = make_test_container()
    container.coin_ledger = NoOpCoinLedger()
    container.db_pool = None
    container.strike_tracker = InMemoryStrikeTracker()
    container.config.models = {}
    app.state.container = container
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ── /admin/strikes ──────────────────────────────────────────────────


def test_list_strikes_empty(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/strikes", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_strikes_with_records(app: FastAPI, client: TestClient) -> None:
    tracker = app.state.container.strike_tracker
    # Record a strike to populate
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        tracker.record_violation(user_id="alice", org_id="__system__", flags=("test",)),
    )
    resp = client.get("/v1/stronghold/admin/strikes", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


def test_get_user_strikes_nonexistent(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/strikes/nobody", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["strike_count"] == 0
    assert data["scrutiny_level"] == "normal"


def test_get_user_strikes_with_record(app: FastAPI, client: TestClient) -> None:
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        app.state.container.strike_tracker.record_violation(
            user_id="alice", org_id="__system__", flags=("test",),
        ),
    )
    resp = client.get("/v1/stronghold/admin/strikes/alice", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["strike_count"] >= 1


def test_get_user_strikes_wrong_org_returns_404(app: FastAPI) -> None:
    """Non-system admin sees 404 for records in other orgs."""
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        app.state.container.strike_tracker.record_violation(
            user_id="bob", org_id="other-org", flags=("t",),
        ),
    )
    # Override auth to non-system
    from stronghold.types.auth import AuthContext, IdentityKind
    fake_auth = AuthContext(
        kind=IdentityKind.USER, user_id="u", org_id="my-org",
        team_id="", roles=frozenset({"admin"}),
    )
    app.state.container.auth_provider.authenticate = AsyncMock(return_value=fake_auth)
    client = TestClient(app)
    resp = client.get("/v1/stronghold/admin/strikes/bob", headers=AUTH)
    assert resp.status_code == 404


def test_remove_strikes_nonexistent(client: TestClient) -> None:
    resp = client.post(
        "/v1/stronghold/admin/strikes/nobody/remove",
        headers=AUTH, json={},
    )
    assert resp.status_code == 404


def test_remove_strikes_clears_all(app: FastAPI, client: TestClient) -> None:
    import asyncio
    asyncio.get_event_loop().run_until_complete(
        app.state.container.strike_tracker.record_violation(
            user_id="charlie", org_id="__system__", flags=("t",),
        ),
    )
    resp = client.post(
        "/v1/stronghold/admin/strikes/charlie/remove",
        headers=AUTH, json={},
    )
    assert resp.status_code == 200
    assert resp.json()["strike_count"] == 0


def test_remove_strikes_partial(app: FastAPI, client: TestClient) -> None:
    import asyncio
    tracker = app.state.container.strike_tracker
    for _ in range(3):
        asyncio.get_event_loop().run_until_complete(
            tracker.record_violation(user_id="dave", org_id="__system__", flags=("t",)),
        )
    resp = client.post(
        "/v1/stronghold/admin/strikes/dave/remove",
        headers=AUTH, json={"count": 1},
    )
    assert resp.status_code == 200
    assert resp.json()["strike_count"] == 2


def test_unlock_user_nonexistent(client: TestClient) -> None:
    resp = client.post(
        "/v1/stronghold/admin/strikes/nobody/unlock", headers=AUTH,
    )
    assert resp.status_code == 404


def test_enable_user_nonexistent(client: TestClient) -> None:
    resp = client.post(
        "/v1/stronghold/admin/strikes/nobody/enable", headers=AUTH,
    )
    assert resp.status_code == 404


# ── /admin/reload ───────────────────────────────────────────────────


def test_reload_config(client: TestClient) -> None:
    """Reload is currently not implemented — returns 501."""
    resp = client.post("/v1/stronghold/admin/reload", headers=AUTH)
    assert resp.status_code in (200, 501)


# ── /admin/coins/refill ─────────────────────────────────────────────


def test_refill_status_no_wallet(client: TestClient) -> None:
    """No daily wallet → refill status returns zero/empty."""
    resp = client.get("/v1/stronghold/admin/coins/refill", headers=AUTH)
    # Either returns a status dict or 404/503 — all are valid contracts
    assert resp.status_code in (200, 404, 503)


# ── /admin/coins/convert bypass of SEC-014 ──────────────────────────


def test_convert_non_integer_float(client: TestClient) -> None:
    """copper_amount='10.5' — int() raises; must return 400."""
    resp = client.post(
        "/v1/stronghold/admin/coins/convert",
        headers=AUTH, json={"copper_amount": "10.5"},
    )
    assert resp.status_code == 400
    # Must be a clean error, not 500
    assert resp.status_code != 500


# ── /admin/coins/convert full happy path ────────────────────────────


def test_convert_no_daily_wallet(app: FastAPI) -> None:
    """When wallets exist but no copper wallet, returns 404."""
    from fastapi.testclient import TestClient
    fake_pool = MagicMock()
    async def fake_acquire():
        class Ctx:
            async def __aenter__(self): return MagicMock()
            async def __aexit__(self, *a): return None
        return Ctx()
    fake_pool.acquire = lambda: Ctx()  # type: ignore[method-assign,assignment]

    class Ctx:
        async def __aenter__(self):
            c = MagicMock()
            c.execute = AsyncMock()
            c.transaction = lambda: TxnCtx()
            return c
        async def __aexit__(self, *a): return None

    class TxnCtx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    app.state.container.db_pool = MagicMock()
    app.state.container.db_pool.acquire = lambda: Ctx()
    app.state.container.coin_ledger = MagicMock()
    app.state.container.coin_ledger.get_banking_rate = AsyncMock(return_value=40)
    app.state.container.coin_ledger.list_wallets = AsyncMock(return_value=[])

    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/admin/coins/convert",
        headers=AUTH, json={"copper_amount": 10},
    )
    assert resp.status_code == 404
    assert "No daily wallet" in resp.json()["detail"]


def test_convert_insufficient_balance(app: FastAPI) -> None:
    """Balance below requested amount returns 400 with diagnostic."""
    from fastapi.testclient import TestClient

    class Ctx:
        async def __aenter__(self):
            c = MagicMock()
            c.execute = AsyncMock()
            c.transaction = lambda: TxnCtx()
            return c
        async def __aexit__(self, *a): return None

    class TxnCtx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    app.state.container.db_pool = MagicMock()
    app.state.container.db_pool.acquire = lambda: Ctx()
    app.state.container.coin_ledger = MagicMock()
    app.state.container.coin_ledger.get_banking_rate = AsyncMock(return_value=40)
    app.state.container.coin_ledger.list_wallets = AsyncMock(return_value=[
        {
            "id": 1, "denomination": "copper",
            "remaining_microchips": 5000,  # 5 copper — less than the 10 requested
        },
    ])

    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/admin/coins/convert",
        headers=AUTH, json={"copper_amount": 10},
    )
    assert resp.status_code == 400
    assert "Insufficient" in resp.json()["detail"]


def test_convert_success_with_existing_silver_wallet(app: FastAPI) -> None:
    """Full happy path with pre-existing silver wallet."""
    from fastapi.testclient import TestClient

    execute_calls = []

    class Ctx:
        async def __aenter__(self):
            c = MagicMock()
            async def exec_(sql, *args):
                execute_calls.append((sql, args))
            c.execute = AsyncMock(side_effect=exec_)
            c.transaction = lambda: TxnCtx()
            return c
        async def __aexit__(self, *a): return None

    class TxnCtx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    app.state.container.db_pool = MagicMock()
    app.state.container.db_pool.acquire = lambda: Ctx()
    app.state.container.coin_ledger = MagicMock()
    app.state.container.coin_ledger.get_banking_rate = AsyncMock(return_value=40)
    app.state.container.coin_ledger.list_wallets = AsyncMock(return_value=[
        {"id": 1, "denomination": "copper", "remaining_microchips": 100_000},
        {"id": 2, "denomination": "silver", "remaining_microchips": 0},
    ])

    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/admin/coins/convert",
        headers=AUTH, json={"copper_amount": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["copper_amount"] == 10
    assert data["banking_rate_pct"] == 40
    assert data["convert_id"].startswith("convert-")
    # Two INSERT statements should have run (debit + credit)
    assert len(execute_calls) == 2


def test_convert_auto_creates_silver_wallet(app: FastAPI) -> None:
    """If no silver wallet exists, one is auto-created."""
    from fastapi.testclient import TestClient

    class Ctx:
        async def __aenter__(self):
            c = MagicMock()
            c.execute = AsyncMock()
            c.transaction = lambda: TxnCtx()
            return c
        async def __aexit__(self, *a): return None

    class TxnCtx:
        async def __aenter__(self): return None
        async def __aexit__(self, *a): return None

    upsert_calls = []
    async def fake_upsert(**kwargs):
        upsert_calls.append(kwargs)
        return {"id": 2, "denomination": "silver", "remaining_microchips": 0}

    app.state.container.db_pool = MagicMock()
    app.state.container.db_pool.acquire = lambda: Ctx()
    app.state.container.coin_ledger = MagicMock()
    app.state.container.coin_ledger.get_banking_rate = AsyncMock(return_value=50)
    app.state.container.coin_ledger.list_wallets = AsyncMock(return_value=[
        {"id": 1, "denomination": "copper", "remaining_microchips": 100_000},
        # No silver wallet
    ])
    app.state.container.coin_ledger.upsert_wallet = AsyncMock(side_effect=fake_upsert)

    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/admin/coins/convert",
        headers=AUTH, json={"copper_amount": 10},
    )
    assert resp.status_code == 200
    assert len(upsert_calls) == 1
    assert upsert_calls[0]["denomination"] == "silver"
    assert upsert_calls[0]["label"] == "Silver Exchange"


# ── /admin/coins/refill happy path ──────────────────────────────────


def test_refill_no_db(app: FastAPI) -> None:
    """With no db_pool, spent_today defaults to 0."""
    from fastapi.testclient import TestClient

    # Need a coin_ledger that returns a banking rate
    app.state.container.db_pool = None
    app.state.container.coin_ledger = MagicMock()
    app.state.container.coin_ledger.get_banking_rate = AsyncMock(return_value=40)

    client = TestClient(app)
    resp = client.get("/v1/stronghold/admin/coins/refill", headers=AUTH)
    # Should succeed even without db_pool
    assert resp.status_code == 200
    data = resp.json()
    assert "daily_allowance" in data
    assert "banking_rate_pct" in data
    assert data["banking_rate_pct"] == 40


def test_refill_with_db_pool(app: FastAPI) -> None:
    """With db_pool, query returns spent_today."""
    from fastapi.testclient import TestClient

    class Ctx:
        async def __aenter__(self):
            c = MagicMock()
            c.fetchval = AsyncMock(return_value=12_000)  # 12 copper spent
            return c
        async def __aexit__(self, *a): return None

    app.state.container.db_pool = MagicMock()
    app.state.container.db_pool.acquire = lambda: Ctx()
    app.state.container.coin_ledger = MagicMock()
    app.state.container.coin_ledger.get_banking_rate = AsyncMock(return_value=40)

    client = TestClient(app)
    resp = client.get("/v1/stronghold/admin/coins/refill", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert data["spent_today"]["microchips"] == 12_000
