"""Persistence layer tests for the Emissary MCP gateway plane.

The asyncpg-backed persisters in ``stronghold.persistence.pg_mcp`` are
exercised here against a hand-rolled in-memory pool/connection shim that
captures every SQL string and parameter set. This unit-tests the SQL
shape and the round-trip through the persister surface without standing
up Postgres. Real DB integration is covered by the e2e suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from stronghold.mcp.emissary import BackendRegistration
from stronghold.persistence.pg_mcp import (
    PgCatalogPersistence,
    PgCompositePersistence,
    PgRegistrationPersistence,
    PgRevocationPersistence,
)
from stronghold.types.security import (
    CatalogEntry,
    CompositeDefinition,
    CompositeStep,
    Provenance,
    RevocationCriteria,
    Scope,
    TargetKind,
    ToolFingerprint,
    TrustTier,
)

# --- in-memory pool/connection shim ----------------------------------------


class _Conn:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self.executes: list[tuple[str, tuple]] = []
        self.fetched_rows: list[dict[str, Any]] = []
        self._store = store
        self._fetch_result: list[dict[str, Any]] = []
        self._fetchrow_result: dict[str, Any] | None = None
        self._delete_count = 0

    def stage_fetch(self, rows: list[dict[str, Any]]) -> None:
        self._fetch_result = rows

    def stage_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_result = row

    def stage_delete_count(self, n: int) -> None:
        self._delete_count = n

    async def execute(self, sql: str, *params: object) -> str:
        self.executes.append((sql.strip(), params))
        return f"DELETE {self._delete_count}"

    async def fetch(self, sql: str, *params: object) -> list[dict[str, Any]]:
        self.executes.append((sql.strip(), params))
        return list(self._fetch_result)

    async def fetchrow(self, sql: str, *params: object) -> dict[str, Any] | None:
        self.executes.append((sql.strip(), params))
        return self._fetchrow_result

    async def __aenter__(self) -> _Conn:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _Pool:
    def __init__(self) -> None:
        self.conn = _Conn([])

    def acquire(self) -> _Conn:
        return self.conn


def _entry() -> CatalogEntry:
    fp = ToolFingerprint(value="fp-x", name="x", schema_hash="sh")
    return CatalogEntry(
        fingerprint=fp,
        trust_tier=TrustTier.T1,
        provenance=Provenance.ADMIN,
        approved_at_scope=Scope.ORG,
        org_id="acme",
        team_id="",
        user_id="",
        allowed_audiences=frozenset({"https://api.example/"}),
        declared_caps=frozenset({"read"}),
        approved_at=datetime.now(UTC),
        approved_by="admin",
    )


# --- catalog --------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_approve_emits_upsert_sql() -> None:
    pool = _Pool()
    persistence = PgCatalogPersistence(pool)  # type: ignore[arg-type]
    await persistence.approve(_entry())
    assert pool.conn.executes
    sql, params = pool.conn.executes[0]
    assert "INSERT INTO mcp_tool_catalog" in sql
    assert "ON CONFLICT" in sql
    # Fingerprint value first, scope second.
    assert params[0] == "fp-x"
    assert params[1] == "org"
    # JSON fields are serialised — sorted lists.
    assert '"https://api.example/"' in str(params[9])
    assert '"read"' in str(params[10])


@pytest.mark.asyncio
async def test_catalog_revoke_with_scope_targets_one_row() -> None:
    pool = _Pool()
    persistence = PgCatalogPersistence(pool)  # type: ignore[arg-type]
    await persistence.revoke("fp-x", scope=Scope.ORG)
    sql, params = pool.conn.executes[0]
    assert sql.startswith("DELETE FROM mcp_tool_catalog")
    assert "approved_at_scope" in sql
    assert params == ("fp-x", "org")


@pytest.mark.asyncio
async def test_catalog_revoke_without_scope_drops_all() -> None:
    pool = _Pool()
    persistence = PgCatalogPersistence(pool)  # type: ignore[arg-type]
    await persistence.revoke("fp-x", scope=None)
    sql, params = pool.conn.executes[0]
    assert sql.startswith("DELETE FROM mcp_tool_catalog")
    assert "approved_at_scope" not in sql
    assert params == ("fp-x",)


@pytest.mark.asyncio
async def test_catalog_load_all_round_trips_a_row() -> None:
    import json

    pool = _Pool()
    pool.conn.stage_fetch(
        [
            {
                "fingerprint_value": "fp-x",
                "approved_at_scope": "org",
                "name": "x",
                "schema_hash": "sh",
                "trust_tier": "t1",
                "provenance": "admin",
                "org_id": "acme",
                "team_id": "",
                "user_id": "",
                "allowed_audiences": json.dumps(["https://api.example/"]),
                "declared_caps": json.dumps(["read"]),
                "approved_at": datetime.now(UTC),
                "approved_by": "admin",
                "expires_at": None,
            },
        ],
    )
    persistence = PgCatalogPersistence(pool)  # type: ignore[arg-type]
    entries = await persistence.load_all()
    assert len(entries) == 1
    e = entries[0]
    assert e.fingerprint.value == "fp-x"
    assert e.fingerprint.name == "x"
    assert e.trust_tier is TrustTier.T1
    assert e.provenance is Provenance.ADMIN
    assert e.approved_at_scope is Scope.ORG
    assert "https://api.example/" in e.allowed_audiences


# --- registrations --------------------------------------------------------


@pytest.mark.asyncio
async def test_registration_upsert_writes_audiences_as_json() -> None:
    pool = _Pool()
    persistence = PgRegistrationPersistence(pool)  # type: ignore[arg-type]
    await persistence.upsert(
        BackendRegistration(
            fingerprint=ToolFingerprint(value="fp-x", name="x", schema_hash="sh"),
            target_kind=TargetKind.REMOTE_PROXY,
            audiences=frozenset({"https://example/"}),
            session_affinity=False,
            metadata={"server_uri": "https://example/mcp"},
        ),
    )
    sql, params = pool.conn.executes[0]
    assert "INSERT INTO mcp_emissary_backends" in sql
    assert "ON CONFLICT" in sql
    assert params[0] == "fp-x"
    assert params[2] == "remote_proxy"
    assert '"https://example/"' in str(params[3])


@pytest.mark.asyncio
async def test_registration_remove_deletes_by_fingerprint() -> None:
    pool = _Pool()
    persistence = PgRegistrationPersistence(pool)  # type: ignore[arg-type]
    await persistence.remove("fp-x")
    sql, params = pool.conn.executes[0]
    assert sql.startswith("DELETE FROM mcp_emissary_backends")
    assert params == ("fp-x",)


@pytest.mark.asyncio
async def test_registration_load_all_round_trips() -> None:
    import json

    pool = _Pool()
    pool.conn.stage_fetch(
        [
            {
                "fingerprint_value": "fp-x",
                "name": "x",
                "target_kind": "remote_proxy",
                "audiences": json.dumps(["https://example/"]),
                "session_affinity": False,
                "metadata": json.dumps({"server_uri": "https://example/mcp"}),
            },
        ],
    )
    persistence = PgRegistrationPersistence(pool)  # type: ignore[arg-type]
    items = await persistence.load_all()
    assert len(items) == 1
    r = items[0]
    assert r.target_kind is TargetKind.REMOTE_PROXY
    assert r.metadata == {"server_uri": "https://example/mcp"}


# --- revocations ----------------------------------------------------------


@pytest.mark.asyncio
async def test_revocation_add_persists_token_id_and_context() -> None:
    pool = _Pool()
    persistence = PgRevocationPersistence(pool)  # type: ignore[arg-type]
    await persistence.add(
        "tok-1",
        RevocationCriteria(
            tool=ToolFingerprint(value="fp-x", name="x", schema_hash="sh"),
            user_id="alice",
            audience="https://api.example/",
            reason="warden flagged",
        ),
    )
    sql, params = pool.conn.executes[0]
    assert "INSERT INTO mcp_keyward_revocations" in sql
    assert params[0] == "tok-1"
    assert params[2] == "warden flagged"
    # tool fingerprint, user id, audience preserved for audit
    assert params[3] == "fp-x"
    assert params[4] == "alice"
    assert params[5] == "https://api.example/"


@pytest.mark.asyncio
async def test_revocation_is_revoked_returns_true_when_row_exists() -> None:
    pool = _Pool()
    pool.conn.stage_fetchrow({"?column?": 1})
    persistence = PgRevocationPersistence(pool)  # type: ignore[arg-type]
    assert await persistence.is_revoked("tok-1") is True


@pytest.mark.asyncio
async def test_revocation_is_revoked_returns_false_when_no_row() -> None:
    pool = _Pool()
    pool.conn.stage_fetchrow(None)
    persistence = PgRevocationPersistence(pool)  # type: ignore[arg-type]
    assert await persistence.is_revoked("tok-not-here") is False


@pytest.mark.asyncio
async def test_revocation_load_active_returns_token_id_set() -> None:
    pool = _Pool()
    pool.conn.stage_fetch(
        [{"token_id": "tok-1"}, {"token_id": "tok-2"}, {"token_id": "tok-3"}],
    )
    persistence = PgRevocationPersistence(pool)  # type: ignore[arg-type]
    active = await persistence.load_active()
    assert active == {"tok-1", "tok-2", "tok-3"}


@pytest.mark.asyncio
async def test_revocation_purge_older_than_returns_count() -> None:
    pool = _Pool()
    pool.conn.stage_delete_count(7)
    persistence = PgRevocationPersistence(pool)  # type: ignore[arg-type]
    cutoff = datetime.now(UTC)
    n = await persistence.purge_older_than(cutoff)
    assert n == 7


# --- composites -----------------------------------------------------------


def _composite() -> CompositeDefinition:
    fp = ToolFingerprint(value="fp-comp", name="triage", schema_hash="sh")
    atomic = ToolFingerprint(value="fp-search", name="search", schema_hash="sh-s")
    return CompositeDefinition(
        fingerprint=fp,
        name="triage",
        description="bug triage",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        steps=(
            CompositeStep(
                id="s1",
                tool=atomic,
                args_template={"q": "$args.q"},
                on_error="abort",
                parallel_group=None,
            ),
        ),
        trust_tier=TrustTier.T1,
    )


@pytest.mark.asyncio
async def test_composite_upsert_persists_steps_as_json() -> None:
    pool = _Pool()
    persistence = PgCompositePersistence(pool)  # type: ignore[arg-type]
    await persistence.upsert(_composite())
    sql, params = pool.conn.executes[0]
    assert "INSERT INTO mcp_composer_definitions" in sql
    assert params[0] == "fp-comp"
    assert "fp-search" in str(params[6])  # steps JSON contains atomic fingerprint


@pytest.mark.asyncio
async def test_composite_load_all_reconstructs_step_graph() -> None:
    import json

    pool = _Pool()
    pool.conn.stage_fetch(
        [
            {
                "fingerprint_value": "fp-comp",
                "name": "triage",
                "description": "bug triage",
                "schema_hash": "sh",
                "input_schema": json.dumps({"type": "object"}),
                "output_schema": json.dumps({"type": "object"}),
                "steps": json.dumps(
                    [
                        {
                            "id": "s1",
                            "tool_fp": "fp-search",
                            "tool_name": "search",
                            "tool_schema_hash": "sh-s",
                            "args_template": {"q": "$args.q"},
                            "on_error": "abort",
                            "parallel_group": None,
                        },
                    ],
                ),
                "trust_tier": "t1",
            },
        ],
    )
    persistence = PgCompositePersistence(pool)  # type: ignore[arg-type]
    items = await persistence.load_all()
    assert len(items) == 1
    d = items[0]
    assert d.fingerprint.value == "fp-comp"
    assert len(d.steps) == 1
    assert d.steps[0].tool.name == "search"
    assert d.steps[0].args_template == {"q": "$args.q"}


# --- write-through wiring through in-memory components --------------------


@pytest.mark.asyncio
async def test_inmemory_catalog_calls_write_through_on_approve_and_revoke() -> None:
    from stronghold.security.tool_catalog import InMemoryToolCatalog

    approves: list[CatalogEntry] = []
    revokes: list[tuple[str, Scope | None]] = []

    catalog = InMemoryToolCatalog(
        persist_approve=approves.append,
        persist_revoke=lambda fp_value, scope: revokes.append((fp_value, scope)),
    )
    entry = _entry()
    catalog.approve(entry.fingerprint, entry)
    catalog.revoke(entry.fingerprint, scope=Scope.ORG)
    assert approves == [entry]
    assert revokes == [("fp-x", Scope.ORG)]


@pytest.mark.asyncio
async def test_inmemory_catalog_hydrate_skips_write_through() -> None:
    from stronghold.security.tool_catalog import InMemoryToolCatalog

    approves: list[CatalogEntry] = []
    catalog = InMemoryToolCatalog(persist_approve=approves.append)
    catalog.hydrate(_entry())
    assert approves == []
    # But the entry is in the cache.
    from stronghold.types.auth import AuthContext, IdentityKind

    auth = AuthContext(user_id="a", org_id="acme", kind=IdentityKind.USER)
    assert catalog.lookup(_entry().fingerprint, auth) is not None
