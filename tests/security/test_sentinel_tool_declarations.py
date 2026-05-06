"""Sentinel tool-declaration validator tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stronghold.security import tool_fingerprint as fingerprinter
from stronghold.security.sentinel.tool_declarations import (
    CatalogUnavailableError,
    ToolDeclarationValidator,
)
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    Scope,
    ToolFingerprint,
    TrustTier,
)


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        username="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _approve(catalog: InMemoryToolCatalog, declaration: dict[str, object]) -> ToolFingerprint:
    fingerprint = fingerprinter.compute(declaration)
    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=TrustTier.T1,
            provenance=Provenance.ADMIN,
            approved_at_scope=Scope.ORG,
            org_id="acme",
            allowed_audiences=frozenset({"https://api.example/"}),
            declared_caps=frozenset({"read"}),
            approved_at=datetime.now(UTC),
            approved_by="admin",
        ),
    )
    return fingerprint


@pytest.mark.asyncio
async def test_all_approved_tools_pass() -> None:
    catalog = InMemoryToolCatalog()
    decl = {"name": "github_search", "description": "Search", "input_schema": {"type": "object"}}
    _approve(catalog, decl)
    validator = ToolDeclarationValidator(catalog)
    verdict = await validator.validate([decl], _alice())
    assert verdict.allowed
    assert verdict.unapproved == ()
    assert verdict.mismatched == ()


@pytest.mark.asyncio
async def test_empty_tools_array_is_allowed() -> None:
    validator = ToolDeclarationValidator(InMemoryToolCatalog())
    verdict = await validator.validate([], _alice())
    assert verdict.allowed


@pytest.mark.asyncio
async def test_unknown_tool_blocks_with_submit_url() -> None:
    catalog = InMemoryToolCatalog()
    decl = {"name": "rogue_export", "description": "Suspicious", "input_schema": {}}
    validator = ToolDeclarationValidator(catalog)
    verdict = await validator.validate([decl], _alice())
    assert verdict.allowed is False
    assert len(verdict.unapproved) == 1
    assert verdict.unapproved[0].name == "rogue_export"
    assert verdict.submit_urls is not None
    assert any("rogue_export" not in url for url in verdict.submit_urls.values()) or any(
        verdict.unapproved[0].value in url for url in verdict.submit_urls.values()
    )


@pytest.mark.asyncio
async def test_schema_drift_reported_as_mismatch_not_unapproved() -> None:
    catalog = InMemoryToolCatalog()
    approved_decl = {
        "name": "github_search",
        "description": "Search",
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }
    _approve(catalog, approved_decl)

    drifted_decl = {
        "name": "github_search",
        "description": "Search",
        "input_schema": {
            "type": "object",
            "properties": {"q": {"type": "string"}, "extra": {"type": "string"}},
        },
    }
    validator = ToolDeclarationValidator(catalog)
    verdict = await validator.validate([drifted_decl], _alice())
    assert verdict.allowed is False
    assert len(verdict.mismatched) == 1
    assert verdict.unapproved == ()


@pytest.mark.asyncio
async def test_mixed_approved_and_unapproved_blocks_entire_request() -> None:
    catalog = InMemoryToolCatalog()
    approved = {"name": "github_search", "description": "", "input_schema": {}}
    unapproved = {"name": "rogue_export", "description": "", "input_schema": {}}
    _approve(catalog, approved)

    validator = ToolDeclarationValidator(catalog)
    verdict = await validator.validate([approved, unapproved], _alice())
    assert verdict.allowed is False
    assert {fp.name for fp in verdict.unapproved} == {"rogue_export"}


@pytest.mark.asyncio
async def test_tool_order_does_not_change_decision() -> None:
    catalog = InMemoryToolCatalog()
    a = {"name": "a", "description": "", "input_schema": {}}
    b = {"name": "b", "description": "", "input_schema": {}}
    c = {"name": "c", "description": "", "input_schema": {}}
    _approve(catalog, a)
    _approve(catalog, b)

    validator = ToolDeclarationValidator(catalog)
    v1 = await validator.validate([a, b, c], _alice())
    v2 = await validator.validate([c, a, b], _alice())
    assert v1.allowed == v2.allowed
    assert {fp.name for fp in v1.unapproved} == {fp.name for fp in v2.unapproved}


@pytest.mark.asyncio
async def test_catalog_unavailable_fails_closed() -> None:
    class BrokenCatalog:
        def lookup(self, fingerprint, auth):  # type: ignore[no-untyped-def]
            raise CatalogUnavailableError("backend down")

        def approvals_for(self, auth):  # type: ignore[no-untyped-def]
            raise CatalogUnavailableError("backend down")

        def fingerprints_with_name(self, name):  # type: ignore[no-untyped-def]
            return frozenset()

        def subscribe_changes(self, callback):  # type: ignore[no-untyped-def]
            return lambda: None

    validator = ToolDeclarationValidator(BrokenCatalog())  # type: ignore[arg-type]
    verdict = await validator.validate(
        [{"name": "x", "description": "", "input_schema": {}}],
        _alice(),
    )
    assert verdict.allowed is False
    assert verdict.fail_closed is True


@pytest.mark.asyncio
async def test_openai_function_format_is_canonicalised() -> None:
    catalog = InMemoryToolCatalog()
    flat = {"name": "x", "description": "y", "input_schema": {"type": "object"}}
    _approve(catalog, flat)

    openai_format = {
        "type": "function",
        "function": {"name": "x", "description": "y", "parameters": {"type": "object"}},
    }
    validator = ToolDeclarationValidator(catalog)
    verdict = await validator.validate([openai_format], _alice())
    assert verdict.allowed is True
