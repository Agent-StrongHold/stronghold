"""In-memory append-only DocumentVersion store (spec §23).

Implements `VersionStore` Protocol from `protocols.canvas_design`.

Storage layers:
  - **delta versions** for normal mutations (small JSON Patch-like blobs)
  - **snapshot versions** every N appends OR on explicit `checkpoint()` —
    full Document JSON for fast restore.

Restore at version V = nearest snapshot ≤ V + apply forward deltas.

Coalescing: same-author same-layer ops within `_COALESCE_WINDOW_S` seconds
collapse into the prior version's delta (per spec §23 edge case 5).

Retention: the default sweep keeps the most recent `_RETAIN_RECENT` versions
plus any `pinned=True` versions plus any `snapshot=…` checkpoints.
"""

from __future__ import annotations

import builtins
import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from stronghold.types.canvas_design import AuthorKind, DocumentVersion
from stronghold.types.errors import (
    DocumentNotFoundError,
    RevertConflictError,
    VersionNotFoundError,
)

# Type alias avoids the `list[DocumentVersion]` annotation getting confused
# with `InMemoryVersionStore.list` method in mypy's scope resolution.
type _VersionList = builtins.list[DocumentVersion]

_SNAPSHOT_EVERY = 25
_COALESCE_WINDOW_S = 5.0
_RETAIN_RECENT = 200
_RETAIN_DAYS = 90


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class InMemoryVersionStore:
    """Tenant-scoped in-memory `VersionStore`.

    Each Document has its own ordered list of versions. Versions are
    immutable; coalescing replaces the most recent entry.

    Per the Protocol contract every read/write takes `tenant_id`. Cross-
    tenant access raises `VersionNotFoundError`.
    """

    def __init__(
        self,
        *,
        snapshot_every: int = _SNAPSHOT_EVERY,
        coalesce_window_seconds: float = _COALESCE_WINDOW_S,
    ) -> None:
        # tenant_id → document_id → _VersionList
        self._versions: dict[str, dict[str, _VersionList]] = {}
        self._snapshot_every = snapshot_every
        self._coalesce_window = timedelta(seconds=coalesce_window_seconds)

    # ── append / checkpoint ─────────────────────────────────────────────

    async def append(
        self,
        document_id: str,
        *,
        tenant_id: str,
        author_id: str,
        author_kind: str,
        delta: dict[str, Any],
        message: str = "",
    ) -> str:
        """Append a delta version; coalesces with prior if within window."""
        existing = self._versions.setdefault(tenant_id, {}).setdefault(document_id, [])
        author_kind_enum = AuthorKind(author_kind)
        prior = existing[-1] if existing else None

        if (
            prior is not None
            and not prior.is_snapshot
            and prior.author_id == author_id
            and prior.author_kind is author_kind_enum
            and self._is_coalescible(prior, delta)
            and (_now() - prior.created_at) <= self._coalesce_window
        ):
            merged = dict(prior.delta)
            merged.update(delta)
            coalesced = dataclasses.replace(prior, delta=merged, message=message or prior.message)
            existing[-1] = coalesced
            return coalesced.id

        ordinal = (prior.ordinal + 1) if prior else 1
        snapshot: dict[str, Any] | None = None
        # Auto-snapshot every N versions (after the first append).
        if (ordinal - 1) % self._snapshot_every == 0 and ordinal > 1:
            snapshot = self._build_snapshot(existing, delta)
        new_version = DocumentVersion(
            id=_new_id(),
            document_id=document_id,
            ordinal=ordinal,
            author_id=author_id,
            author_kind=author_kind_enum,
            parent_version_id=prior.id if prior else None,
            delta=dict(delta),
            snapshot=snapshot,
            message=message,
        )
        existing.append(new_version)
        return new_version.id

    async def checkpoint(
        self,
        document_id: str,
        *,
        tenant_id: str,
        author_id: str,
        message: str,
    ) -> str:
        """Create a snapshot version with the current restored state."""
        existing = self._versions.setdefault(tenant_id, {}).setdefault(document_id, [])
        prior = existing[-1] if existing else None
        snapshot = self._restore_state(existing) if existing else {}
        ordinal = (prior.ordinal + 1) if prior else 1
        version = DocumentVersion(
            id=_new_id(),
            document_id=document_id,
            ordinal=ordinal,
            author_id=author_id,
            author_kind=AuthorKind.SYSTEM if prior is None else AuthorKind.USER,
            parent_version_id=prior.id if prior else None,
            delta={},
            snapshot=snapshot,
            message=message,
        )
        existing.append(version)
        return version.id

    # ── reads ──────────────────────────────────────────────────────────

    async def get(
        self,
        document_id: str,
        version_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Restore the document state at the given version."""
        versions = self._for(tenant_id, document_id)
        idx = self._index_of(versions, version_id)
        if idx is None:
            raise VersionNotFoundError(f"version {version_id!r} not found")
        return self._restore_state(versions[: idx + 1])

    async def list(
        self,
        document_id: str,
        *,
        tenant_id: str,
        limit: int = 100,
        before: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """List versions newest-first; `before` filters by created_at."""
        versions = self._for(tenant_id, document_id)
        ordered = sorted(versions, key=lambda v: v.ordinal, reverse=True)
        if before is not None:
            ordered = [v for v in ordered if v.created_at < before]
        return [_to_dict(v) for v in ordered[:limit]]

    async def revert(
        self,
        document_id: str,
        version_id: str,
        *,
        tenant_id: str,
        author_id: str,
    ) -> str:
        """Append a new version that restores the state at `version_id`."""
        versions = self._for(tenant_id, document_id)
        idx = self._index_of(versions, version_id)
        if idx is None:
            raise VersionNotFoundError(f"version {version_id!r} not found")
        if idx == len(versions) - 1:
            # Reverting to HEAD is a no-op; surface explicitly so callers
            # don't accidentally treat it as a meaningful branch.
            raise RevertConflictError("cannot revert to current HEAD")
        target = versions[idx]
        snapshot = self._restore_state(versions[: idx + 1])
        new_version = DocumentVersion(
            id=_new_id(),
            document_id=document_id,
            ordinal=versions[-1].ordinal + 1,
            author_id=author_id,
            author_kind=AuthorKind.USER,
            parent_version_id=target.id,
            delta={"reverted_from": target.id},
            snapshot=snapshot,
            message=f"revert to v{target.ordinal}",
        )
        versions.append(new_version)
        return new_version.id

    # ── extras (not in Protocol; useful for tests/sweeps) ───────────────

    def pin(self, document_id: str, version_id: str, *, tenant_id: str) -> None:
        versions = self._for(tenant_id, document_id)
        idx = self._index_of(versions, version_id)
        if idx is None:
            raise VersionNotFoundError(f"version {version_id!r} not found")
        versions[idx] = dataclasses.replace(versions[idx], pinned=True)

    def retain_sweep(
        self,
        *,
        tenant_id: str,
        document_id: str,
        keep_recent: int = _RETAIN_RECENT,
        keep_days: int = _RETAIN_DAYS,
    ) -> int:
        """Drop older non-checkpoint, non-pinned versions; returns count removed."""
        versions = self._for(tenant_id, document_id)
        if len(versions) <= keep_recent:
            return 0
        cutoff = _now() - timedelta(days=keep_days)
        keep: _VersionList = []
        # always keep the last keep_recent versions
        head, tail = versions[:-keep_recent], versions[-keep_recent:]
        for v in head:
            if v.pinned or v.is_snapshot or v.created_at >= cutoff:
                keep.append(v)
        keep.extend(tail)
        removed = len(versions) - len(keep)
        self._versions[tenant_id][document_id] = keep
        return removed

    def head_id(self, document_id: str, *, tenant_id: str) -> str | None:
        versions = self._for(tenant_id, document_id)
        return versions[-1].id if versions else None

    def count(self, document_id: str, *, tenant_id: str) -> int:
        return len(self._for(tenant_id, document_id))

    # ── helpers ────────────────────────────────────────────────────────

    def _for(self, tenant_id: str, document_id: str) -> _VersionList:
        bucket = self._versions.get(tenant_id)
        if bucket is None:
            raise VersionNotFoundError(f"tenant {tenant_id!r} has no versions")
        versions = bucket.get(document_id)
        if versions is None:
            raise DocumentNotFoundError(f"document {document_id!r} has no versions")
        return versions

    @staticmethod
    def _index_of(versions: _VersionList, version_id: str) -> int | None:
        for i, v in enumerate(versions):
            if v.id == version_id:
                return i
        return None

    @staticmethod
    def _is_coalescible(prior: DocumentVersion, new_delta: dict[str, Any]) -> bool:
        """Same-layer same-kind deltas can be coalesced."""
        prior_keys = set(prior.delta.keys())
        new_keys = set(new_delta.keys())
        if not prior_keys or not new_keys:
            return False
        # If both deltas reference the same scalar field on the same target,
        # they can collapse (e.g. dragging a layer emits many move deltas).
        return prior_keys == new_keys

    def _restore_state(self, versions: _VersionList) -> dict[str, Any]:
        """Compute full state at the end of `versions` by applying snapshots+deltas."""
        if not versions:
            return {}
        # Find nearest snapshot ≤ end
        snapshot_idx = -1
        for i in range(len(versions) - 1, -1, -1):
            if versions[i].is_snapshot:
                snapshot_idx = i
                break
        if snapshot_idx == -1:
            state: dict[str, Any] = {}
            forward = versions
        else:
            snap = versions[snapshot_idx].snapshot
            assert snap is not None
            state = dict(snap)
            forward = versions[snapshot_idx + 1 :]
        for v in forward:
            for k, val in v.delta.items():
                state[k] = val
        return state

    def _build_snapshot(
        self,
        existing: _VersionList,
        new_delta: dict[str, Any],
    ) -> dict[str, Any]:
        snap = self._restore_state(existing)
        for k, v in new_delta.items():
            snap[k] = v
        return snap


def _to_dict(version: DocumentVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "document_id": version.document_id,
        "ordinal": version.ordinal,
        "author_id": version.author_id,
        "author_kind": version.author_kind.value,
        "parent_version_id": version.parent_version_id,
        "delta": dict(version.delta),
        "snapshot": dict(version.snapshot) if version.snapshot is not None else None,
        "message": version.message,
        "pinned": version.pinned,
        "created_at": version.created_at.isoformat(),
    }
