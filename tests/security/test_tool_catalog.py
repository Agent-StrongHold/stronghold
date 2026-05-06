"""ToolCatalog scope-walk semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.auth import SYSTEM_ORG_ID, AuthContext, IdentityKind
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    Scope,
    ToolFingerprint,
    TrustTier,
)

# --- helpers ----------------------------------------------------------------


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        username="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _bob_other_team() -> AuthContext:
    return AuthContext(
        user_id="bob",
        username="bob",
        org_id="acme",
        team_id="data",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _victor_other_org() -> AuthContext:
    return AuthContext(
        user_id="victor",
        username="victor",
        org_id="rival",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _system() -> AuthContext:
    return AuthContext(
        user_id="system",
        org_id=SYSTEM_ORG_ID,
        kind=IdentityKind.SYSTEM,
        auth_method="api_key",
    )


def _fp(name: str = "github_search") -> ToolFingerprint:
    return ToolFingerprint(value=f"fp-{name}", name=name, schema_hash=f"sh-{name}")


def _entry(
    fingerprint: ToolFingerprint,
    *,
    scope: Scope,
    org_id: str = "",
    team_id: str = "",
    user_id: str = "",
    tier: TrustTier = TrustTier.T1,
) -> CatalogEntry:
    return CatalogEntry(
        fingerprint=fingerprint,
        trust_tier=tier,
        provenance=Provenance.ADMIN,
        approved_at_scope=scope,
        org_id=org_id,
        team_id=team_id,
        user_id=user_id,
        allowed_audiences=frozenset({"https://api.example/"}),
        declared_caps=frozenset({"read"}),
        approved_at=datetime.now(UTC),
        approved_by="admin",
    )


# --- tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_fingerprint_returns_none() -> None:
    catalog = InMemoryToolCatalog()
    assert catalog.lookup(_fp(), _alice()) is None


@pytest.mark.asyncio
async def test_org_scope_visible_to_org_member() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.ORG, org_id="acme"))
    assert catalog.lookup(fingerprint, _alice()) is not None
    assert catalog.lookup(fingerprint, _bob_other_team()) is not None  # same org


@pytest.mark.asyncio
async def test_org_scope_invisible_to_other_org() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.ORG, org_id="acme"))
    assert catalog.lookup(fingerprint, _victor_other_org()) is None


@pytest.mark.asyncio
async def test_team_scope_invisible_to_other_team_in_same_org() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(
        fingerprint,
        _entry(fingerprint, scope=Scope.TEAM, org_id="acme", team_id="platform"),
    )
    assert catalog.lookup(fingerprint, _alice()) is not None
    assert catalog.lookup(fingerprint, _bob_other_team()) is None


@pytest.mark.asyncio
async def test_user_scope_invisible_to_other_user_in_same_team() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(
        fingerprint,
        _entry(
            fingerprint,
            scope=Scope.USER,
            org_id="acme",
            team_id="platform",
            user_id="alice",
        ),
    )
    assert catalog.lookup(fingerprint, _alice()) is not None
    bob_same_team = AuthContext(
        user_id="bob",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )
    assert catalog.lookup(fingerprint, bob_same_team) is None


@pytest.mark.asyncio
async def test_platform_scope_visible_to_all_members() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.PLATFORM))
    assert catalog.lookup(fingerprint, _alice()) is not None
    assert catalog.lookup(fingerprint, _victor_other_org()) is not None


@pytest.mark.asyncio
async def test_system_principal_sees_everything_regardless_of_scope() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(
        fingerprint,
        _entry(fingerprint, scope=Scope.USER, org_id="acme", team_id="platform", user_id="alice"),
    )
    assert catalog.lookup(fingerprint, _system()) is not None


@pytest.mark.asyncio
async def test_approvals_for_returns_the_union_across_scope_chain() -> None:
    catalog = InMemoryToolCatalog()
    platform_tool = _fp("platform_lookup")
    org_tool = _fp("org_runbook")
    other_team_tool = _fp("other_team_runbook")
    alice_only = _fp("alice_personal")

    catalog.approve(platform_tool, _entry(platform_tool, scope=Scope.PLATFORM))
    catalog.approve(org_tool, _entry(org_tool, scope=Scope.ORG, org_id="acme"))
    catalog.approve(
        other_team_tool,
        _entry(other_team_tool, scope=Scope.TEAM, org_id="acme", team_id="data"),
    )
    catalog.approve(
        alice_only,
        _entry(alice_only, scope=Scope.USER, org_id="acme", team_id="platform", user_id="alice"),
    )

    visible = catalog.approvals_for(_alice())
    assert platform_tool in visible
    assert org_tool in visible
    assert alice_only in visible
    assert other_team_tool not in visible


@pytest.mark.asyncio
async def test_revoke_at_scope_only_removes_that_scope() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.ORG, org_id="acme"))
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.PLATFORM))
    catalog.revoke(fingerprint, scope=Scope.ORG)
    # Still visible via PLATFORM.
    assert catalog.lookup(fingerprint, _alice()) is not None
    catalog.revoke(fingerprint, scope=Scope.PLATFORM)
    assert catalog.lookup(fingerprint, _alice()) is None


@pytest.mark.asyncio
async def test_revoke_without_scope_removes_all_approvals() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.ORG, org_id="acme"))
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.PLATFORM))
    catalog.revoke(fingerprint)
    assert catalog.lookup(fingerprint, _alice()) is None
    assert catalog.lookup(fingerprint, _system()) is None


@pytest.mark.asyncio
async def test_subscribe_changes_fires_on_approve_and_revoke() -> None:
    catalog = InMemoryToolCatalog()
    seen: list[int] = []
    catalog.subscribe_changes(lambda: seen.append(1))
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.PLATFORM))
    catalog.revoke(fingerprint)
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_unsubscribe_stops_callbacks() -> None:
    catalog = InMemoryToolCatalog()
    seen: list[int] = []
    unsubscribe = catalog.subscribe_changes(lambda: seen.append(1))
    fingerprint = _fp()
    catalog.approve(fingerprint, _entry(fingerprint, scope=Scope.PLATFORM))
    unsubscribe()
    catalog.revoke(fingerprint)
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_fingerprints_with_name_supports_rug_pull_diagnostics() -> None:
    catalog = InMemoryToolCatalog()
    v1 = ToolFingerprint(value="fp-v1", name="github_search", schema_hash="sh1")
    v2 = ToolFingerprint(value="fp-v2", name="github_search", schema_hash="sh2")
    catalog.approve(v1, _entry(v1, scope=Scope.PLATFORM))
    matches = catalog.fingerprints_with_name("github_search")
    assert "fp-v1" in matches
    assert "fp-v2" not in matches  # never approved
    catalog.approve(v2, _entry(v2, scope=Scope.PLATFORM))
    assert {"fp-v1", "fp-v2"} <= catalog.fingerprints_with_name("github_search")
