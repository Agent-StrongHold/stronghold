"""PostgreSQL persistence for the Emissary MCP gateway plane.

Four small persisters, one per long-lived component:

- ``PgCatalogPersistence``       — ToolCatalog approve / revoke / load_all
- ``PgRegistrationPersistence``  — Emissary backend registrations upsert / remove / load_all
- ``PgRevocationPersistence``    — Keyward token revocations add / is_revoked / load_active
- ``PgCompositePersistence``     — Composer composite definitions upsert / remove / load_all

Each persister is a thin asyncpg wrapper that mirrors the in-memory
component's mutation surface. The in-memory components remain the
read path (cache); the persisters are the write-through and the source
of truth across restarts.

Schema lives in migrations/012_mcp_emissary_plane.sql. The table layout
intentionally uses JSONB for set/dict fields so that queries can filter
on JSON paths if richer admin views are added later.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from stronghold.mcp.emissary import BackendRegistration
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

if TYPE_CHECKING:
    from collections.abc import Callable

    import asyncpg


# --- ToolCatalog -----------------------------------------------------------


class PgCatalogPersistence:
    """ToolCatalog write-through + restart-time hydration."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def approve(self, entry: CatalogEntry) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_tool_catalog
                       (fingerprint_value, approved_at_scope, name, schema_hash,
                        trust_tier, provenance, org_id, team_id, user_id,
                        allowed_audiences, declared_caps, approved_at,
                        approved_by, expires_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                   ON CONFLICT (fingerprint_value, approved_at_scope) DO UPDATE SET
                       name = EXCLUDED.name,
                       schema_hash = EXCLUDED.schema_hash,
                       trust_tier = EXCLUDED.trust_tier,
                       provenance = EXCLUDED.provenance,
                       org_id = EXCLUDED.org_id,
                       team_id = EXCLUDED.team_id,
                       user_id = EXCLUDED.user_id,
                       allowed_audiences = EXCLUDED.allowed_audiences,
                       declared_caps = EXCLUDED.declared_caps,
                       approved_at = EXCLUDED.approved_at,
                       approved_by = EXCLUDED.approved_by,
                       expires_at = EXCLUDED.expires_at""",
                entry.fingerprint.value,
                entry.approved_at_scope.value,
                entry.fingerprint.name,
                entry.fingerprint.schema_hash,
                entry.trust_tier.value,
                entry.provenance.value,
                entry.org_id,
                entry.team_id,
                entry.user_id,
                json.dumps(sorted(entry.allowed_audiences)),
                json.dumps(sorted(entry.declared_caps)),
                entry.approved_at,
                entry.approved_by,
                entry.expires_at,
            )

    async def revoke(
        self,
        fingerprint_value: str,
        scope: Scope | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            if scope is None:
                await conn.execute(
                    "DELETE FROM mcp_tool_catalog WHERE fingerprint_value = $1",
                    fingerprint_value,
                )
            else:
                await conn.execute(
                    """DELETE FROM mcp_tool_catalog
                       WHERE fingerprint_value = $1 AND approved_at_scope = $2""",
                    fingerprint_value,
                    scope.value,
                )

    async def load_all(self) -> list[CatalogEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM mcp_tool_catalog")
        return [_row_to_catalog_entry(row) for row in rows]


def _row_to_catalog_entry(row: dict[str, Any]) -> CatalogEntry:
    return CatalogEntry(
        fingerprint=ToolFingerprint(
            value=row["fingerprint_value"],
            name=row["name"],
            schema_hash=row["schema_hash"],
        ),
        trust_tier=TrustTier(row["trust_tier"]),
        provenance=Provenance(row["provenance"]),
        approved_at_scope=Scope(row["approved_at_scope"]),
        org_id=row["org_id"],
        team_id=row["team_id"],
        user_id=row["user_id"],
        allowed_audiences=frozenset(json.loads(row["allowed_audiences"])),
        declared_caps=frozenset(json.loads(row["declared_caps"])),
        approved_at=row["approved_at"],
        approved_by=row["approved_by"],
        expires_at=row["expires_at"],
    )


# --- Emissary backend registrations ---------------------------------------


class PgRegistrationPersistence:
    """Emissary register_backend / unregister write-through + hydration."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert(self, registration: BackendRegistration) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_emissary_backends
                       (fingerprint_value, name, target_kind, audiences,
                        session_affinity, metadata)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (fingerprint_value) DO UPDATE SET
                       name = EXCLUDED.name,
                       target_kind = EXCLUDED.target_kind,
                       audiences = EXCLUDED.audiences,
                       session_affinity = EXCLUDED.session_affinity,
                       metadata = EXCLUDED.metadata""",
                registration.fingerprint.value,
                registration.fingerprint.name,
                registration.target_kind.value,
                json.dumps(sorted(registration.audiences)),
                registration.session_affinity,
                json.dumps(registration.metadata),
            )

    async def remove(self, fingerprint_value: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mcp_emissary_backends WHERE fingerprint_value = $1",
                fingerprint_value,
            )

    async def load_all(self) -> list[BackendRegistration]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM mcp_emissary_backends")
        return [_row_to_registration(row) for row in rows]


def _row_to_registration(row: dict[str, Any]) -> BackendRegistration:
    # schema_hash is not stored on this table — fingerprint identity comes
    # from the catalog. We rebuild ToolFingerprint with an empty schema_hash
    # since the registration doesn't need it for routing.
    return BackendRegistration(
        fingerprint=ToolFingerprint(
            value=row["fingerprint_value"],
            name=row["name"],
            schema_hash="",
        ),
        target_kind=TargetKind(row["target_kind"]),
        audiences=frozenset(json.loads(row["audiences"])),
        session_affinity=row["session_affinity"],
        metadata=dict(json.loads(row["metadata"])),
    )


# --- Keyward revocations --------------------------------------------------


class PgRevocationPersistence:
    """Keyward revocation set write-through + hydration."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def add(self, token_id: str, criteria: RevocationCriteria) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_keyward_revocations
                       (token_id, revoked_at, reason,
                        revoked_by_tool_fp, revoked_by_user_id, revoked_by_audience)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (token_id) DO NOTHING""",
                token_id,
                datetime.now(UTC),
                criteria.reason,
                criteria.tool.value if criteria.tool else None,
                criteria.user_id,
                criteria.audience,
            )

    async def is_revoked(self, token_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM mcp_keyward_revocations WHERE token_id = $1",
                token_id,
            )
        return row is not None

    async def load_active(self) -> set[str]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT token_id FROM mcp_keyward_revocations")
        return {str(row["token_id"]) for row in rows}

    async def purge_older_than(self, cutoff: datetime) -> int:
        """Drop revocation rows older than ``cutoff`` (cleanup task).

        Revocations only matter while the corresponding token could still
        be valid; once expired, the row is dead weight. Caller decides
        cutoff = now - max_token_ttl - grace.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM mcp_keyward_revocations WHERE revoked_at < $1",
                cutoff,
            )
        # asyncpg returns "DELETE <n>" — parse the count for callers.
        try:
            return int(str(result).split()[-1])
        except (IndexError, ValueError):
            return 0


# --- Composer composite definitions ---------------------------------------


class PgCompositePersistence:
    """Composer register / remove write-through + hydration."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert(self, definition: CompositeDefinition) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO mcp_composer_definitions
                       (fingerprint_value, name, description, schema_hash,
                        input_schema, output_schema, steps, trust_tier)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT (fingerprint_value) DO UPDATE SET
                       name = EXCLUDED.name,
                       description = EXCLUDED.description,
                       schema_hash = EXCLUDED.schema_hash,
                       input_schema = EXCLUDED.input_schema,
                       output_schema = EXCLUDED.output_schema,
                       steps = EXCLUDED.steps,
                       trust_tier = EXCLUDED.trust_tier""",
                definition.fingerprint.value,
                definition.name,
                definition.description,
                definition.fingerprint.schema_hash,
                json.dumps(definition.input_schema),
                json.dumps(definition.output_schema),
                json.dumps([_step_to_dict(s) for s in definition.steps]),
                definition.trust_tier.value,
            )

    async def remove(self, fingerprint_value: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM mcp_composer_definitions WHERE fingerprint_value = $1",
                fingerprint_value,
            )

    async def load_all(self) -> list[CompositeDefinition]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM mcp_composer_definitions")
        return [_row_to_composite(row) for row in rows]


def _step_to_dict(step: CompositeStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "tool_fp": step.tool.value,
        "tool_name": step.tool.name,
        "tool_schema_hash": step.tool.schema_hash,
        "args_template": step.args_template,
        "on_error": step.on_error,
        "parallel_group": step.parallel_group,
    }


def _dict_to_step(payload: dict[str, Any]) -> CompositeStep:
    return CompositeStep(
        id=str(payload["id"]),
        tool=ToolFingerprint(
            value=str(payload["tool_fp"]),
            name=str(payload["tool_name"]),
            schema_hash=str(payload.get("tool_schema_hash", "")),
        ),
        args_template=dict(payload.get("args_template") or {}),
        on_error=str(payload.get("on_error", "abort")),
        parallel_group=payload.get("parallel_group"),
    )


def _row_to_composite(row: dict[str, Any]) -> CompositeDefinition:
    return CompositeDefinition(
        fingerprint=ToolFingerprint(
            value=row["fingerprint_value"],
            name=row["name"],
            schema_hash=row["schema_hash"],
        ),
        name=row["name"],
        description=row["description"],
        input_schema=dict(json.loads(row["input_schema"])),
        output_schema=dict(json.loads(row["output_schema"])),
        steps=tuple(_dict_to_step(s) for s in json.loads(row["steps"])),
        trust_tier=TrustTier(row["trust_tier"]),
    )


# --- bulk hydration -------------------------------------------------------


async def hydrate_emissary_plane(
    *,
    catalog_persistence: PgCatalogPersistence,
    registration_persistence: PgRegistrationPersistence,
    revocation_persistence: PgRevocationPersistence,
    composite_persistence: PgCompositePersistence,
    catalog_apply: Callable[[CatalogEntry], None],
    registration_apply: Callable[[BackendRegistration], None],
    revocation_apply: Callable[[str], None],
    composite_apply: Callable[[CompositeDefinition], None],
) -> dict[str, int]:
    """Load every persisted record into in-memory components at startup.

    Each ``*_apply`` argument is a callable that accepts the loaded
    record and inserts it into the in-memory cache. This keeps the
    persistence module decoupled from the in-memory implementations.
    """
    catalog_entries = await catalog_persistence.load_all()
    for entry in catalog_entries:
        catalog_apply(entry)

    registrations = await registration_persistence.load_all()
    for registration in registrations:
        registration_apply(registration)

    revoked = await revocation_persistence.load_active()
    for token_id in revoked:
        revocation_apply(token_id)

    composites = await composite_persistence.load_all()
    for composite in composites:
        composite_apply(composite)

    return {
        "catalog_entries": len(catalog_entries),
        "registrations": len(registrations),
        "revocations": len(revoked),
        "composites": len(composites),
    }
