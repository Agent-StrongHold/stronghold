"""In-memory canvas-design implementations for tests + dev (spec §02).

These satisfy the Protocol shapes in `stronghold.protocols.canvas_design`
without any external dependencies. Suitable for unit + integration tests
and for the dev `STRONGHOLD_CONFIG=dev.yaml` local stack. Production uses
Postgres-backed adapters (deferred).

All operations enforce tenant isolation: every read/write requires
tenant_id and silently filters non-matching rows. There is no admin
escape hatch in this fake — that's intentional.
"""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime
from typing import Any

from stronghold.types.canvas_design import (
    Document,
    DocumentKind,
    Page,
)
from stronghold.types.errors import (
    ConcurrentEditError,
    DocumentNotFoundError,
    EmptyDocumentError,
    InvalidPageOrderingError,
    MasterInUseError,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class InMemoryDocumentStore:
    """Tenant-scoped in-memory store satisfying DocumentStore (spec §02).

    Documents are stored as {document_id → Document}. Every method takes a
    `tenant_id` keyword argument; cross-tenant access raises
    DocumentNotFoundError.
    """

    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}

    # ── lifecycle ──────────────────────────────────────────────────────

    async def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        name: str,
        kind: str,
    ) -> str:
        """Create an empty document; returns its id."""
        doc_id = _new_id()
        doc_kind = DocumentKind(kind)
        doc = Document(
            id=doc_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            name=name,
            kind=doc_kind,
        )
        self._docs[doc_id] = doc
        return doc_id

    async def get(self, document_id: str, *, tenant_id: str) -> dict[str, Any]:
        """Load a document; cross-tenant returns DocumentNotFoundError."""
        doc = self._get_or_404(document_id, tenant_id)
        return _to_dict(doc)

    async def update(
        self,
        document_id: str,
        *,
        tenant_id: str,
        delta: dict[str, Any],
        expected_version: int | None = None,
    ) -> int:
        """Apply a typed delta; bumps version. Raises ConcurrentEditError on mismatch.

        Supported delta keys:
          - `name`: rename
          - `archived`: bool
          - `brand_kit_id`, `style_lock_id`: optional ids
          - `metadata`: dict (replaces existing)
          - `pages`: tuple[Page, ...] (full replace; ordering must be gapless)
          - `master_pages`: tuple[Page, ...] (full replace)
        """
        doc = self._get_or_404(document_id, tenant_id)
        if expected_version is not None and expected_version != doc.version:
            raise ConcurrentEditError(
                f"expected version {expected_version}, current is {doc.version}"
            )
        # Validation surfaces upstream errors (e.g. PAGE_ORDERING_NOT_GAPLESS)
        # converted to InvalidPageOrderingError for the caller's sake.
        try:
            updated = dataclasses.replace(
                doc,
                version=doc.version + 1,
                updated_at=_now(),
                **{k: v for k, v in delta.items() if k in _UPDATABLE_FIELDS},
            )
        except Exception as exc:  # noqa: BLE001 — re-raise as canvas-domain error
            if "PAGE_ORDERING" in str(exc):
                raise InvalidPageOrderingError(str(exc)) from exc
            raise
        self._docs[document_id] = updated
        return updated.version

    async def list_for_owner(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        archived: bool = False,
    ) -> list[dict[str, Any]]:
        """List documents owned by user within tenant."""
        return [
            _to_dict(d)
            for d in self._docs.values()
            if d.tenant_id == tenant_id and d.owner_id == owner_id and d.archived == archived
        ]

    async def archive(self, document_id: str, *, tenant_id: str) -> None:
        """Soft-delete (sets archived=true); idempotent."""
        doc = self._get_or_404(document_id, tenant_id)
        self._docs[document_id] = dataclasses.replace(
            doc, archived=True, version=doc.version + 1, updated_at=_now()
        )

    # ── pages (helpers used by higher-level layers; not part of the
    #          DocumentStore Protocol itself but valuable for tests) ────

    async def add_page(
        self,
        document_id: str,
        page: Page,
        *,
        tenant_id: str,
        ordering: int | None = None,
    ) -> int:
        """Insert page at `ordering` (defaults to end); shifts later pages."""
        doc = self._get_or_404(document_id, tenant_id)
        target = ordering if ordering is not None else len(doc.pages)
        if target < 0 or target > len(doc.pages):
            raise InvalidPageOrderingError(
                f"insert ordering {target} outside [0, {len(doc.pages)}]"
            )
        new_pages = tuple(
            dataclasses.replace(p, ordering=p.ordering + 1) if p.ordering >= target else p
            for p in doc.pages
        )
        page_at_target = dataclasses.replace(page, ordering=target)
        new_pages = (*new_pages, page_at_target)
        new_pages = tuple(sorted(new_pages, key=lambda p: p.ordering))
        return await self.update(document_id, tenant_id=tenant_id, delta={"pages": new_pages})

    async def delete_page(self, document_id: str, page_id: str, *, tenant_id: str) -> int:
        """Remove a page; renumbers later pages to remain gapless."""
        doc = self._get_or_404(document_id, tenant_id)
        if not any(p.id == page_id for p in doc.pages):
            raise DocumentNotFoundError(f"page {page_id} not in document {document_id}")
        kept = [p for p in doc.pages if p.id != page_id]
        new_pages = tuple(dataclasses.replace(p, ordering=i) for i, p in enumerate(kept))
        return await self.update(document_id, tenant_id=tenant_id, delta={"pages": new_pages})

    async def reorder_pages(
        self,
        document_id: str,
        ordering: tuple[str, ...],
        *,
        tenant_id: str,
    ) -> int:
        """Apply explicit (page_id, ...) ordering; preserves master_id."""
        doc = self._get_or_404(document_id, tenant_id)
        existing = {p.id: p for p in doc.pages}
        if set(existing) != set(ordering):
            raise InvalidPageOrderingError("reorder must reference exactly the existing page ids")
        new_pages = tuple(
            dataclasses.replace(existing[pid], ordering=i) for i, pid in enumerate(ordering)
        )
        return await self.update(document_id, tenant_id=tenant_id, delta={"pages": new_pages})

    async def delete_master(
        self,
        document_id: str,
        master_id: str,
        *,
        tenant_id: str,
    ) -> int:
        """Remove a master; rejects if any page still references it."""
        doc = self._get_or_404(document_id, tenant_id)
        if any(p.master_id == master_id for p in doc.pages):
            raise MasterInUseError(f"master {master_id} is referenced by at least one page")
        kept_masters = tuple(m for m in doc.master_pages if m.id != master_id)
        return await self.update(
            document_id, tenant_id=tenant_id, delta={"master_pages": kept_masters}
        )

    # ── helpers for export pre-condition (spec §13) ─────────────────────

    async def assert_non_empty(self, document_id: str, *, tenant_id: str) -> None:
        """Raise EmptyDocumentError if doc has 0 pages; used by export pipeline."""
        doc = self._get_or_404(document_id, tenant_id)
        if doc.page_count == 0:
            raise EmptyDocumentError(f"document {document_id} has no pages")

    # ── internal ───────────────────────────────────────────────────────

    def _get_or_404(self, document_id: str, tenant_id: str) -> Document:
        doc = self._docs.get(document_id)
        if doc is None or doc.tenant_id != tenant_id:
            raise DocumentNotFoundError(f"document {document_id} not found")
        return doc


_UPDATABLE_FIELDS = frozenset(
    {
        "name",
        "archived",
        "brand_kit_id",
        "style_lock_id",
        "metadata",
        "pages",
        "master_pages",
    }
)


def _to_dict(doc: Document) -> dict[str, Any]:
    """Serialise a Document to a JSON-friendly dict (transport form)."""
    return {
        "id": doc.id,
        "tenant_id": doc.tenant_id,
        "owner_id": doc.owner_id,
        "name": doc.name,
        "kind": doc.kind.value,
        "page_count": doc.page_count,
        "version": doc.version,
        "archived": doc.archived,
        "brand_kit_id": doc.brand_kit_id,
        "style_lock_id": doc.style_lock_id,
        "metadata": dict(doc.metadata),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }
