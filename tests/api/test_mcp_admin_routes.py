"""MCP admin route contract tests.

Exercises /v1/stronghold/admin/mcp/tools list/get/approve/revoke against
a Container with the Emissary plane wired. Auth uses the StaticKeyAuthProvider
in read-write mode (admin role) — same pattern as other admin tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.mcp_admin import router as mcp_admin_router
from stronghold.mcp.composer import Composer
from stronghold.mcp.emissary import Emissary
from stronghold.security import tool_fingerprint as fingerprinter
from stronghold.security.keyward import Keyward, KeywardConfig
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    Scope,
    TrustTier,
    WardenVerdict,
)
from tests.api.test_coverage_routes import _build_container

ADMIN_HEADER = {"Authorization": "Bearer sk-test"}
_SIGNING_KEY = "mcp-admin-route-test-key-32-bytes-min!!"


class _CleanWarden:
    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


def _wire_plane(container) -> tuple[InMemoryToolCatalog, Emissary]:  # type: ignore[no-untyped-def]
    catalog = InMemoryToolCatalog()
    keyward = Keyward(catalog=catalog, config=KeywardConfig(signing_key=_SIGNING_KEY))
    emissary = Emissary(
        catalog=catalog,
        keyward=keyward,
        warden=_CleanWarden(),  # type: ignore[arg-type]
        composer=Composer(),
        invokers={},
    )
    container.mcp_tool_catalog = catalog
    container.emissary = emissary
    return catalog, emissary


@pytest.fixture
def app_with_plane() -> tuple[FastAPI, InMemoryToolCatalog, Emissary]:
    app = FastAPI()
    app.include_router(mcp_admin_router)
    container = _build_container()
    catalog, emissary = _wire_plane(container)
    app.state.container = container
    return app, catalog, emissary


@pytest.fixture
def app_without_plane() -> FastAPI:
    app = FastAPI()
    app.include_router(mcp_admin_router)
    container = _build_container()
    # mcp_tool_catalog and emissary stay None — endpoints must 503.
    app.state.container = container
    return app


def _seed(catalog: InMemoryToolCatalog, name: str = "github_search") -> str:
    decl = {"name": name, "description": "", "input_schema": {}}
    fingerprint = fingerprinter.compute(decl)
    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=TrustTier.T1,
            provenance=Provenance.ADMIN,
            approved_at_scope=Scope.PLATFORM,
            allowed_audiences=frozenset({"https://api.example/"}),
            declared_caps=frozenset({"read"}),
            approved_at=datetime.now(UTC),
            approved_by="admin",
        ),
    )
    return fingerprint.value


# --- 503 when plane not wired -----------------------------------------------


def test_list_returns_503_when_plane_not_wired(app_without_plane: FastAPI) -> None:
    with TestClient(app_without_plane) as client:
        resp = client.get("/v1/stronghold/admin/mcp/tools", headers=ADMIN_HEADER)
    assert resp.status_code == 503


# --- auth -----------------------------------------------------------------


def test_list_without_auth_is_401(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.get("/v1/stronghold/admin/mcp/tools")
    assert resp.status_code == 401


# --- list -----------------------------------------------------------------


def test_list_returns_seeded_tool(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, catalog, _ = app_with_plane
    fingerprint_value = _seed(catalog)
    with TestClient(app) as client:
        resp = client.get("/v1/stronghold/admin/mcp/tools", headers=ADMIN_HEADER)
    assert resp.status_code == 200
    body = resp.json()
    fingerprints = [t["fingerprint"] for t in body["tools"]]
    assert fingerprint_value in fingerprints


def test_list_empty_when_no_tools_approved(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.get("/v1/stronghold/admin/mcp/tools", headers=ADMIN_HEADER)
    assert resp.status_code == 200
    assert resp.json()["tools"] == []


# --- get one --------------------------------------------------------------


def test_get_one_returns_full_entry(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, catalog, _ = app_with_plane
    fingerprint_value = _seed(catalog)
    with TestClient(app) as client:
        resp = client.get(
            f"/v1/stronghold/admin/mcp/tools/{fingerprint_value}",
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fingerprint"] == fingerprint_value
    assert body["name"] == "github_search"
    assert body["trust_tier"] == "t1"
    assert body["approved_at_scope"] == "platform"
    assert "https://api.example/" in body["allowed_audiences"]


def test_get_unknown_fingerprint_404(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.get(
            "/v1/stronghold/admin/mcp/tools/fp-does-not-exist",
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 404


# --- approve --------------------------------------------------------------


def test_approve_creates_catalog_entry_and_backend(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, catalog, emissary = app_with_plane
    body = {
        "name": "issue_search",
        "description": "Search issues",
        "input_schema": {"type": "object"},
        "target_kind": "remote_proxy",
        "audiences": ["https://api.linear.app/"],
        "declared_caps": ["read:issues"],
        "trust_tier": "t1",
        "provenance": "admin",
        "approved_at_scope": "platform",
        "metadata": {"server_uri": "https://api.linear.app/mcp"},
    }
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stronghold/admin/mcp/tools",
            json=body,
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 201
    fingerprint_value = resp.json()["fingerprint"]
    # Catalog: fingerprint is now visible to a system principal walk.
    from stronghold.types.auth import SYSTEM_AUTH

    visible = {fp.value for fp in catalog.approvals_for(SYSTEM_AUTH)}
    assert fingerprint_value in visible
    # Emissary: the backend is registered (look-up by fingerprint string).
    assert fingerprint_value in emissary._registrations


def test_approve_missing_name_returns_400(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stronghold/admin/mcp/tools",
            json={
                "description": "",
                "input_schema": {},
                "target_kind": "remote_proxy",
                "audiences": ["https://x/"],
                "approved_at_scope": "platform",
                "metadata": {},
            },
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 400
    assert "name" in resp.json()["detail"]


def test_approve_invalid_target_kind_returns_400(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stronghold/admin/mcp/tools",
            json={
                "name": "x",
                "description": "",
                "input_schema": {},
                "target_kind": "not_a_real_kind",
                "audiences": ["https://x/"],
                "approved_at_scope": "platform",
                "metadata": {},
            },
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 400


def test_approve_empty_audiences_returns_400(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.post(
            "/v1/stronghold/admin/mcp/tools",
            json={
                "name": "x",
                "description": "",
                "input_schema": {},
                "target_kind": "first_party",
                "audiences": [],
                "approved_at_scope": "platform",
                "metadata": {},
            },
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 400
    assert "audiences" in resp.json()["detail"]


# --- revoke ---------------------------------------------------------------


def test_revoke_removes_catalog_entry(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, catalog, _ = app_with_plane
    fingerprint_value = _seed(catalog)
    with TestClient(app) as client:
        resp = client.delete(
            f"/v1/stronghold/admin/mcp/tools/{fingerprint_value}",
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 200
    assert resp.json()["revoked"] == fingerprint_value
    # After revoke, list returns empty.
    with TestClient(app) as client:
        resp = client.get("/v1/stronghold/admin/mcp/tools", headers=ADMIN_HEADER)
    assert resp.json()["tools"] == []


def test_revoke_unknown_fingerprint_404(
    app_with_plane: tuple[FastAPI, InMemoryToolCatalog, Emissary],
) -> None:
    app, _, _ = app_with_plane
    with TestClient(app) as client:
        resp = client.delete(
            "/v1/stronghold/admin/mcp/tools/fp-nope",
            headers=ADMIN_HEADER,
        )
    assert resp.status_code == 404
