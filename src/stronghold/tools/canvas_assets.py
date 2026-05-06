"""Asset library (spec §18).

Tenant-scoped registry for characters, props, uploads (and template
thumbnails). Three search modes — tag, substring, semantic-stub — and
drag-onto-canvas via `asset_insert(asset_id, page_id) → Layer`.

The "embedding" search uses a deterministic hash-based mock as a
stand-in for CLIP. Production swaps an `ImageEmbedder` adapter.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from stronghold.types.canvas_design import (
    Layer,
    LayerTransform,
    RasterSource,
)
from stronghold.types.errors import (
    AssetNotFoundError,
    AssetReferenceInUseError,
    AssetUploadValidationError,
    EmbeddingUnavailableError,
)
from stronghold.types.security import Provenance, TrustTier

if TYPE_CHECKING:
    from collections.abc import Sequence


_EMBED_DIM = 32  # tiny hash-based mock; production uses 512


class AssetKind(StrEnum):
    CHARACTER = "character"
    PROP = "prop"
    UPLOAD = "upload"
    TEMPLATE_THUMB = "template_thumb"


class UploadSourceKind(StrEnum):
    PHOTO = "photo"
    LOGO = "logo"
    ILLUSTRATION = "illustration"
    SVG = "svg"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Asset dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Asset:
    id: str
    tenant_id: str
    owner_id: str
    kind: AssetKind
    name: str
    primary_blob_id: str
    description: str = ""
    tags: tuple[str, ...] = ()
    thumbnail_blob_id: str | None = None
    reference_sheet_blob_ids: tuple[str, ...] = ()
    embedding: tuple[float, ...] | None = None
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)
    trust_tier: TrustTier = TrustTier.T3
    provenance: Provenance = Provenance.USER
    uses_count: int = 0
    archived: bool = False
    created_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Mock embedder (hash-based, deterministic)
# ---------------------------------------------------------------------------


class HashEmbedder:
    """Mock CLIP-like embedder. Hashes input bytes into a fixed-dim vector
    in [-1, 1]. Deterministic + fast. Production swaps a real CLIP adapter."""

    def __init__(self, *, dim: int = _EMBED_DIM, fail: bool = False) -> None:
        self._dim = dim
        self._fail = fail

    async def embed(self, image: bytes) -> tuple[float, ...]:
        if self._fail:
            raise EmbeddingUnavailableError("embedder offline (mock)")
        digest = hashlib.sha256(image).digest()
        # Repeat the digest enough times to cover dim, then map bytes → [-1, 1]
        repeated = (digest * ((self._dim // len(digest)) + 1))[: self._dim]
        return tuple((b - 128) / 128.0 for b in repeated)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = float(sum(a[i] * b[i] for i in range(n)))
    norm_a = float(sum(a[i] * a[i] for i in range(n))) ** 0.5
    norm_b = float(sum(b[i] * b[i] for i in range(n))) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


_SVG_SCRIPT_RE = re.compile(rb"<\s*script\b[^>]*>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)


def _sanitise_svg(blob: bytes) -> bytes:
    """Remove <script> elements from SVG; matches spec §18 edge case 4."""
    return _SVG_SCRIPT_RE.sub(b"", blob)


def _slug_tags(tags: Sequence[str]) -> tuple[str, ...]:
    return tuple(t.strip().lower().replace(" ", "-") for t in tags)


class InMemoryAssetStore:
    """Tenant-scoped Asset CRUD with three search modes + reference counts."""

    def __init__(self, *, embedder: HashEmbedder | None = None) -> None:
        self._assets: dict[str, dict[str, Asset]] = {}
        # tenant → asset_id → set[document_id] referencing the asset
        self._refs: dict[str, dict[str, set[str]]] = {}
        self._embedder = embedder or HashEmbedder()

    async def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        kind: AssetKind,
        name: str,
        primary_blob_id: str,
        primary_blob_bytes: bytes | None = None,
        tags: Sequence[str] = (),
        description: str = "",
        rights_acknowledged: bool = True,
        source_kind: UploadSourceKind | None = None,
    ) -> Asset:
        if kind is AssetKind.UPLOAD and not rights_acknowledged:
            raise AssetUploadValidationError("uploads require explicit rights_acknowledged=True")
        if (
            kind is AssetKind.UPLOAD
            and source_kind is UploadSourceKind.SVG
            and primary_blob_bytes is not None
        ):
            primary_blob_bytes = _sanitise_svg(primary_blob_bytes)

        embedding: tuple[float, ...] | None = None
        if primary_blob_bytes is not None:
            try:
                embedding = await self._embedder.embed(primary_blob_bytes)
            except EmbeddingUnavailableError:
                embedding = None

        asset = Asset(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            owner_id=owner_id,
            kind=kind,
            name=name,
            primary_blob_id=primary_blob_id,
            description=description,
            tags=_slug_tags(tags),
            embedding=embedding,
            metadata={"source_kind": source_kind.value} if source_kind else {},
        )
        self._assets.setdefault(tenant_id, {})[asset.id] = asset
        return asset

    async def get(self, asset_id: str, *, tenant_id: str) -> Asset:
        bucket = self._assets.get(tenant_id, {})
        if asset_id not in bucket:
            raise AssetNotFoundError(f"asset {asset_id!r} not found")
        return bucket[asset_id]

    async def search(
        self,
        *,
        tenant_id: str,
        query: str = "",
        kind: AssetKind | None = None,
        tags: Sequence[str] = (),
        mode: str = "tag",
        query_bytes: bytes | None = None,
        limit: int = 20,
    ) -> list[Asset]:
        bucket = self._assets.get(tenant_id, {})
        results: list[Asset] = list(bucket.values())
        if kind is not None:
            results = [a for a in results if a.kind is kind]
        if mode == "tag" and tags:
            tag_set = set(_slug_tags(tags))
            results = [a for a in results if tag_set.intersection(a.tags)]
        elif mode == "substring":
            q = query.lower()
            results = [a for a in results if q in a.name.lower() or q in a.description.lower()]
        elif mode == "semantic":
            if query_bytes is None:
                raise AssetUploadValidationError("semantic search requires query_bytes")
            try:
                qvec = await self._embedder.embed(query_bytes)
            except EmbeddingUnavailableError:
                # Fall back to substring search on name
                q = query.lower()
                results = [a for a in results if q in a.name.lower()]
            else:
                scored = [(a, _cosine(qvec, a.embedding or ())) for a in results]
                scored.sort(key=lambda pair: pair[1], reverse=True)
                results = [a for a, _ in scored]
        return [a for a in results if not a.archived][:limit]

    async def archive(self, asset_id: str, *, tenant_id: str) -> None:
        asset = await self.get(asset_id, tenant_id=tenant_id)
        bucket = self._assets[tenant_id]
        bucket[asset_id] = dataclasses.replace(asset, archived=True, updated_at=datetime.now(UTC))

    async def hard_delete(self, asset_id: str, *, tenant_id: str) -> None:
        refs = self._refs.get(tenant_id, {}).get(asset_id, set())
        if refs:
            raise AssetReferenceInUseError(
                f"asset {asset_id!r} is referenced by {len(refs)} document(s)"
            )
        self._assets.get(tenant_id, {}).pop(asset_id, None)

    async def list_for_tenant(
        self,
        *,
        tenant_id: str,
        kind: AssetKind | None = None,
    ) -> list[Asset]:
        bucket = self._assets.get(tenant_id, {})
        return [a for a in bucket.values() if not a.archived and (kind is None or a.kind is kind)]

    def insert_into_layer(
        self,
        asset: Asset,
        *,
        page_id: str,
        position: tuple[int, int] = (0, 0),
        z_index: int = 100,
    ) -> Layer:
        """Build a Layer from an asset for drag-onto-canvas."""
        return Layer(
            id=str(uuid.uuid4()),
            name=asset.name,
            source=RasterSource(
                blob_id=asset.primary_blob_id,
                width=0,
                height=0,
            ),
            transform=LayerTransform(x=position[0], y=position[1]),
            z_index=z_index,
            metadata={"source_asset_id": asset.id, "source_page_id": page_id},
        )

    # ── reference counting (used by hard_delete protection) ────────────

    def record_reference(
        self,
        asset_id: str,
        document_id: str,
        *,
        tenant_id: str,
    ) -> None:
        bucket = self._refs.setdefault(tenant_id, {}).setdefault(asset_id, set())
        bucket.add(document_id)

    def release_reference(
        self,
        asset_id: str,
        document_id: str,
        *,
        tenant_id: str,
    ) -> None:
        bucket = self._refs.get(tenant_id, {}).get(asset_id)
        if bucket is not None:
            bucket.discard(document_id)
