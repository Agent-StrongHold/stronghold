"""Sentinel ToolDeclarationValidator hook in chat completions endpoint.

When the inbound /v1/chat/completions request body carries a ``tools[]``
array, the chat handler validates each declaration against the principal's
approved tool catalog before forwarding to the agent pipeline. Today
``tools[]`` is not surfaced downstream, so this is a forward-compat safety
net; the moment a future change wires inbound tools[] to the LLM, they are
already gated.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.chat import router as chat_router
from stronghold.security import tool_fingerprint as fingerprinter
from stronghold.security.sentinel.tool_declarations import ToolDeclarationValidator
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    Scope,
    TrustTier,
)
from tests.api.test_coverage_routes import _build_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app_without_validator() -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    container = _build_container()
    # tool_declaration_validator stays None — chat.py must skip the gate.
    app.state.container = container
    return app


@pytest.fixture
def app_with_validator() -> tuple[FastAPI, InMemoryToolCatalog]:
    app = FastAPI()
    app.include_router(chat_router)
    container = _build_container()
    catalog = InMemoryToolCatalog()
    container.mcp_tool_catalog = catalog
    container.tool_declaration_validator = ToolDeclarationValidator(catalog=catalog)
    app.state.container = container
    return app, catalog


def _approve(catalog: InMemoryToolCatalog, declaration: dict[str, object]) -> None:
    fingerprint = fingerprinter.compute(declaration)
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


# --- legacy (no validator wired) ------------------------------------------


def test_inbound_tools_without_validator_does_not_block(
    app_without_validator: FastAPI,
) -> None:
    """Container without a tool_declaration_validator wired must not gate
    inbound tools[] — preserves prior behaviour for any deployment that
    hasn't yet wired the Emissary plane."""
    with TestClient(app_without_validator) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [{"name": "any_tool", "description": "", "input_schema": {}}],
            },
            headers=AUTH_HEADER,
        )
    # The validator is the only thing that would 4xx here on tools[];
    # without it we either 200 (agent succeeded) or 5xx (no test agent
    # configured). What we MUST NOT see is a 403 with the validator's
    # error_kind payload.
    assert resp.status_code != 403


# --- validator wired -------------------------------------------------------


def test_inbound_no_tools_field_skips_validation(
    app_with_validator: tuple[FastAPI, InMemoryToolCatalog],
) -> None:
    app, _ = app_with_validator
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hello"}]},
            headers=AUTH_HEADER,
        )
    assert resp.status_code != 403


def test_inbound_empty_tools_array_skips_validation(
    app_with_validator: tuple[FastAPI, InMemoryToolCatalog],
) -> None:
    app, _ = app_with_validator
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [],
            },
            headers=AUTH_HEADER,
        )
    assert resp.status_code != 403


def test_inbound_unapproved_tool_returns_403(
    app_with_validator: tuple[FastAPI, InMemoryToolCatalog],
) -> None:
    app, _ = app_with_validator
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [
                    {"name": "rogue", "description": "", "input_schema": {}},
                ],
            },
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "rogue" in detail["unapproved"]
    assert "submit_urls" in detail


def test_inbound_approved_tool_passes_validation(
    app_with_validator: tuple[FastAPI, InMemoryToolCatalog],
) -> None:
    app, catalog = app_with_validator
    decl = {"name": "approved_tool", "description": "", "input_schema": {}}
    _approve(catalog, decl)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [decl],
            },
            headers=AUTH_HEADER,
        )
    # Approved tool must not be 403 from the validator (200 from agent or
    # downstream 5xx are both acceptable — what we're verifying is that
    # the validator did not block).
    assert resp.status_code != 403


def test_inbound_mixed_blocks_on_first_unapproved(
    app_with_validator: tuple[FastAPI, InMemoryToolCatalog],
) -> None:
    app, catalog = app_with_validator
    approved = {"name": "approved", "description": "", "input_schema": {}}
    rogue = {"name": "rogue", "description": "", "input_schema": {}}
    _approve(catalog, approved)
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "tools": [approved, rogue],
            },
            headers=AUTH_HEADER,
        )
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert "rogue" in detail["unapproved"]
    assert "approved" not in detail["unapproved"]
