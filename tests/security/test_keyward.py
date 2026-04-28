"""Keyward credential issuer tests."""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest

from stronghold.security.keyward import Keyward, KeywardConfig
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    RevocationCriteria,
    Scope,
    TokenRequest,
    ToolFingerprint,
    TrustTier,
)

_SIGNING_KEY = "test-signing-key-do-not-use-in-prod"


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        username="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _fp(name: str = "github_search") -> ToolFingerprint:
    return ToolFingerprint(value=f"fp-{name}", name=name, schema_hash=f"sh-{name}")


def _approve(
    catalog: InMemoryToolCatalog,
    fingerprint: ToolFingerprint,
    *,
    audiences: frozenset[str] = frozenset({"https://api.github.com"}),
    caps: frozenset[str] = frozenset({"read:issues"}),
) -> None:
    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=TrustTier.T1,
            provenance=Provenance.ADMIN,
            approved_at_scope=Scope.ORG,
            org_id="acme",
            allowed_audiences=audiences,
            declared_caps=caps,
            approved_at=datetime.now(UTC),
            approved_by="admin",
        ),
    )


def _keyward(
    catalog: InMemoryToolCatalog,
    *,
    per_audience_ttl: dict[str, int] | None = None,
) -> Keyward:
    return Keyward(
        catalog=catalog,
        config=KeywardConfig(
            signing_key=_SIGNING_KEY,
            per_audience_ttl_seconds=per_audience_ttl or {},
        ),
    )


# --- happy path -------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_for_approved_tool_returns_signed_token() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint)
    keyward = _keyward(catalog)

    result = await keyward.issue(
        TokenRequest(
            tool=fingerprint,
            auth=_alice(),
            audience="https://api.github.com",
            requested_scopes=frozenset({"read:issues"}),
            call_id="c1",
        ),
    )
    assert result.token is not None
    assert result.token.audience == "https://api.github.com"
    assert result.token.scopes == frozenset({"read:issues"})

    decoded = jwt.decode(
        result.token.serialized,
        _SIGNING_KEY,
        algorithms=["HS256"],
        audience="https://api.github.com",
    )
    assert decoded["sub"] == "alice"
    assert decoded["org"] == "acme"
    assert decoded["scope"] == "read:issues"
    assert decoded["tool_fp"] == fingerprint.value
    assert decoded["call_id"] == "c1"
    assert decoded["jti"] == result.token.id


# --- refusals ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuse_unapproved_tool() -> None:
    keyward = _keyward(InMemoryToolCatalog())
    result = await keyward.issue(
        TokenRequest(
            tool=_fp(),
            auth=_alice(),
            audience="https://api.github.com",
            requested_scopes=frozenset(),
            call_id="c1",
        ),
    )
    assert result.token is None
    assert result.error_kind == "unauthorized"


@pytest.mark.asyncio
async def test_refuse_audience_outside_allowed_set() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint)
    keyward = _keyward(catalog)
    result = await keyward.issue(
        TokenRequest(
            tool=fingerprint,
            auth=_alice(),
            audience="https://api.gitlab.com",  # not in allowed_audiences
            requested_scopes=frozenset({"read:issues"}),
            call_id="c1",
        ),
    )
    assert result.token is None
    assert result.error_kind == "audience_denied"


@pytest.mark.asyncio
async def test_refuse_scope_escalation() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint, caps=frozenset({"read:issues"}))
    keyward = _keyward(catalog)
    result = await keyward.issue(
        TokenRequest(
            tool=fingerprint,
            auth=_alice(),
            audience="https://api.github.com",
            requested_scopes=frozenset({"read:issues", "delete:repo"}),
            call_id="c1",
        ),
    )
    assert result.token is None
    assert result.error_kind == "scope_escalation"


# --- TTL --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_ttl_15_minutes() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint)
    keyward = _keyward(catalog)
    result = await keyward.issue(
        TokenRequest(
            tool=fingerprint,
            auth=_alice(),
            audience="https://api.github.com",
            requested_scopes=frozenset({"read:issues"}),
            call_id="c1",
        ),
    )
    assert result.token is not None
    assert result.token.ttl_seconds == 900


@pytest.mark.asyncio
async def test_per_audience_ttl_override() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint, audiences=frozenset({"https://hris.example"}))
    keyward = _keyward(catalog, per_audience_ttl={"https://hris.example": 120})
    result = await keyward.issue(
        TokenRequest(
            tool=fingerprint,
            auth=_alice(),
            audience="https://hris.example",
            requested_scopes=frozenset({"read:issues"}),
            call_id="c1",
        ),
    )
    assert result.token is not None
    assert result.token.ttl_seconds == 120


# --- revocation -------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_by_token_id_marks_introspection() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint)
    keyward = _keyward(catalog)
    result = await keyward.issue(
        TokenRequest(
            tool=fingerprint,
            auth=_alice(),
            audience="https://api.github.com",
            requested_scopes=frozenset({"read:issues"}),
            call_id="c1",
        ),
    )
    assert result.token is not None
    await keyward.revoke(RevocationCriteria(token_id=result.token.id, reason="test"))
    status = await keyward.introspect(result.token.id)
    assert status is not None
    assert status.revoked is True


@pytest.mark.asyncio
async def test_revoke_by_tool_revokes_all_active_for_that_tool() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint)
    keyward = _keyward(catalog)

    tokens = []
    for i in range(3):
        result = await keyward.issue(
            TokenRequest(
                tool=fingerprint,
                auth=_alice(),
                audience="https://api.github.com",
                requested_scopes=frozenset({"read:issues"}),
                call_id=f"c{i}",
            ),
        )
        assert result.token is not None
        tokens.append(result.token)

    await keyward.revoke(RevocationCriteria(tool=fingerprint, reason="kill switch"))
    for token in tokens:
        status = await keyward.introspect(token.id)
        assert status is not None
        assert status.revoked is True


@pytest.mark.asyncio
async def test_revoke_is_idempotent() -> None:
    catalog = InMemoryToolCatalog()
    fingerprint = _fp()
    _approve(catalog, fingerprint)
    keyward = _keyward(catalog)
    await keyward.revoke(RevocationCriteria(token_id="nonexistent"))
    await keyward.revoke(RevocationCriteria(token_id="nonexistent"))


@pytest.mark.asyncio
async def test_introspect_unknown_token_returns_none() -> None:
    keyward = _keyward(InMemoryToolCatalog())
    assert await keyward.introspect("never-issued") is None


# --- safety -----------------------------------------------------------------


def test_keyward_refuses_to_start_without_signing_key() -> None:
    with pytest.raises(ValueError, match="signing_key"):
        Keyward(catalog=InMemoryToolCatalog(), config=KeywardConfig(signing_key=""))
