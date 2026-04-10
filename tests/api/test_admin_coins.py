"""Tests for admin coin endpoints using NoOpCoinLedger."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.admin import router as admin_router
from stronghold.quota.coins import NoOpCoinLedger
from tests.fakes import make_test_container

AUTH = {"Authorization": "Bearer sk-test", "X-Stronghold-Request": "1"}


@pytest.fixture
def admin_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)

    container = make_test_container()
    container.coin_ledger = NoOpCoinLedger()
    # Add models to config so pricing table can build
    container.config.models = {
        "gpt-4": {
            "provider": "openai",
            "tier": "flagship",
            "quality": 0.9,
            "coin_cost_base_microchips": 100,
            "coin_cost_per_1k_input_microchips": 50,
            "coin_cost_per_1k_output_microchips": 100,
        },
        "gpt-3.5": {
            "provider": "openai",
            "tier": "small",
            "quality": 0.6,
            "coin_cost_base_microchips": 10,
            "coin_cost_per_1k_input_microchips": 5,
            "coin_cost_per_1k_output_microchips": 10,
        },
        "bad-entry": "not-a-dict",  # Should be skipped
    }
    app.state.container = container
    return app


@pytest.fixture
def client(admin_app: FastAPI) -> TestClient:
    return TestClient(admin_app)


# ── /admin/coins/denominations ──────────────────────────────────────


def test_get_coin_denominations(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/coins/denominations", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "microchips_per_copper" in data
    assert "factors" in data


def test_denominations_requires_auth(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/coins/denominations")
    assert resp.status_code == 401


# ── /admin/coins/pricing ────────────────────────────────────────────


def test_get_coin_pricing(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/coins/pricing", headers=AUTH)
    assert resp.status_code == 200
    data = resp.json()
    assert "denominations" in data
    assert "models" in data
    # Two valid models, "bad-entry" skipped
    assert len(data["models"]) == 2
    # Sorted by quality descending — gpt-4 (0.9) first
    assert data["models"][0]["model"] == "gpt-4"
    assert data["models"][1]["model"] == "gpt-3.5"
    # Each entry has required fields
    for entry in data["models"]:
        assert "provider" in entry
        assert "tier" in entry
        assert "base" in entry
        assert "per_1k_input" in entry
        assert "per_1k_output" in entry
        assert "example_1k_cost" in entry
        assert "pricing_version" in entry


def test_pricing_exchange_rates_in_response(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/coins/pricing", headers=AUTH)
    data = resp.json()
    rates = data["denominations"]["exchange_rates"]
    assert "copper" in rates
    assert "silver" in rates
    assert "gold" in rates


# ── /admin/coins/wallets GET ────────────────────────────────────────


def test_list_coin_wallets_empty(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/admin/coins/wallets", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"wallets": []}


def test_list_coin_wallets_with_filters(client: TestClient) -> None:
    resp = client.get(
        "/v1/stronghold/admin/coins/wallets?owner_type=user&owner_id=alice",
        headers=AUTH,
    )
    assert resp.status_code == 200


# ── /admin/coins/wallets PUT ────────────────────────────────────────


def test_upsert_coin_wallet_missing_owner_type(client: TestClient) -> None:
    resp = client.put(
        "/v1/stronghold/admin/coins/wallets",
        headers=AUTH,
        json={"owner_id": "u1"},
    )
    assert resp.status_code == 400
    assert "owner_type" in resp.json()["detail"]


def test_upsert_coin_wallet_missing_owner_id(client: TestClient) -> None:
    resp = client.put(
        "/v1/stronghold/admin/coins/wallets",
        headers=AUTH,
        json={"owner_type": "user"},
    )
    assert resp.status_code == 400


def test_upsert_coin_wallet_org_without_org_id(client: TestClient) -> None:
    """Org wallets require org_id when system auth."""
    resp = client.put(
        "/v1/stronghold/admin/coins/wallets",
        headers=AUTH,
        json={"owner_type": "org", "owner_id": "o1"},
    )
    assert resp.status_code == 400
    assert "org_id" in resp.json()["detail"]


def test_upsert_coin_wallet_noop_returns_503(client: TestClient) -> None:
    """NoOpCoinLedger raises RuntimeError → 503."""
    resp = client.put(
        "/v1/stronghold/admin/coins/wallets",
        headers=AUTH,
        json={
            "owner_type": "user",
            "owner_id": "alice",
            "org_id": "acme",
            "budget_amount": 100,
        },
    )
    assert resp.status_code == 503
    assert "PostgreSQL" in resp.json()["detail"]


def test_upsert_coin_wallet_db_ready(admin_app: FastAPI) -> None:
    """When coin_ledger accepts upsert, returns the wallet."""
    admin_app.state.container.coin_ledger.upsert_wallet = AsyncMock(
        return_value={"wallet_id": 1, "owner_type": "user", "owner_id": "alice"},
    )
    client = TestClient(admin_app)
    resp = client.put(
        "/v1/stronghold/admin/coins/wallets",
        headers=AUTH,
        json={
            "owner_type": "user",
            "owner_id": "alice",
            "org_id": "acme",
            "budget_amount": 100,
            "budget_denomination": "copper",
            "soft_limit_ratio": 0.7,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["wallet_id"] == 1


def test_upsert_coin_wallet_value_error_returns_400(admin_app: FastAPI) -> None:
    admin_app.state.container.coin_ledger.upsert_wallet = AsyncMock(
        side_effect=ValueError("bad input"),
    )
    client = TestClient(admin_app)
    resp = client.put(
        "/v1/stronghold/admin/coins/wallets",
        headers=AUTH,
        json={
            "owner_type": "user",
            "owner_id": "alice",
            "org_id": "acme",
        },
    )
    assert resp.status_code == 400
    assert "bad input" in resp.json()["detail"]
