"""Canvas Studio design-system protocols — companion to types.canvas_design.

Sibling to `stronghold.protocols.canvas`, which exposes the OPERATIONAL
runtime protocols (CanvasStore, ImageGenClient, CompositorService) used by
the existing canvas tool. This module exposes the DESIGN-system protocols
derived from the 33-spec system: backends + stores for the Da Vinci
ecosystem (preflight, versioning, budgets, brand kits, assets, corrections,
critics, learnings, manuscript import, translation, audio, LoRA training,
embeddings).

Implementations slot in via the DI container; business logic depends only
on these Protocol shapes. Per CLAUDE.md Build Rule #5: no direct external
imports.

Each protocol references its design spec in `agents/davinci/specs/`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import datetime

    from stronghold.types.canvas_design import (
        BrandKit,
        Budget,
        BudgetScope,
        BudgetStatus,
        CanvasLearning,
        CanvasLearningScope,
        CheckResult,
        Correction,
        CorrectionContext,
        CorrectionKind,
        CorrectionSource,
        CostForecast,
        Effect,
        EffectKind,
        LearningRuleKind,
        Mask,
        MaskOrigin,
        PreflightReport,
        StyleLock,
    )


# ---------------------------------------------------------------------------
# Generative + masking (specs §03, §04)
# ---------------------------------------------------------------------------


@runtime_checkable
class CanvasBackend(Protocol):
    """Generative + raster backend: txt2img, img2img, inpaint, outpaint, upscale."""

    async def generate(
        self,
        prompt: str,
        *,
        tier: str = "draft",
        aspect_ratio: str = "1:1",
        count: int = 1,
        negative_prompt: str = "",
        reference_images: Sequence[bytes] = (),
        lora_id: str | None = None,
    ) -> list[bytes]:
        """Text-to-image generation. Returns N PNG byte buffers."""
        ...

    async def refine(
        self,
        source_image: bytes,
        prompt: str,
        *,
        strength: float = 0.6,
        reference_images: Sequence[bytes] = (),
    ) -> bytes:
        """img2img refine of an existing layer."""
        ...

    async def inpaint(
        self,
        source_image: bytes,
        mask: Mask,
        prompt: str,
        *,
        reference_images: Sequence[bytes] = (),
        strength: float = 0.8,
    ) -> bytes:
        """Mask-driven inpaint (spec §04)."""
        ...

    async def outpaint(
        self,
        source_image: bytes,
        direction: str,
        pixels: int,
        prompt: str,
    ) -> bytes:
        """Extend canvas in a direction with generative fill (spec §04)."""
        ...

    async def upscale(
        self,
        source_image: bytes,
        factor: int,
        *,
        model: str | None = None,
    ) -> bytes:
        """Upscale by 2x or 4x via Real-ESRGAN/topaz/etc (spec §04)."""
        ...


@runtime_checkable
class MaskGenerator(Protocol):
    """Strategy-routed mask producer (spec §03)."""

    async def create(
        self,
        origin: MaskOrigin,
        *,
        layer_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Mask:
        """Create a mask via the named strategy."""
        ...

    def combine(self, op: str, masks: Sequence[Mask]) -> Mask:
        """Boolean op over masks: union | subtract | intersect | invert."""
        ...


# ---------------------------------------------------------------------------
# Style lock (spec §09)
# ---------------------------------------------------------------------------


@runtime_checkable
class StyleLockChecker(Protocol):
    """Drift scoring against a style lock (spec §09)."""

    async def score(
        self,
        layer_bytes: bytes,
        lock: StyleLock,
    ) -> float:
        """Vision-LLM drift score 0..1 (0=perfect, 1=totally off)."""
        ...

    async def extract_palette(
        self,
        image_bytes: bytes,
        *,
        k: int = 5,
    ) -> tuple[str, ...]:
        """K-means / extcolors palette extraction; returns hex strings."""
        ...

    async def describe(self, image_bytes: bytes) -> str:
        """Vision-LLM textual style description."""
        ...


# ---------------------------------------------------------------------------
# Charts (spec §12)
# ---------------------------------------------------------------------------


@runtime_checkable
class ChartRenderer(Protocol):
    """Chart spec → vector layer (spec §12)."""

    def render(
        self,
        spec: dict[str, Any],
        *,
        size_px: tuple[int, int] = (800, 600),
        palette: Sequence[str] = (),
    ) -> bytes:
        """Render a Vega-Lite spec to SVG bytes."""
        ...


# ---------------------------------------------------------------------------
# Document persistence (spec §02)
# ---------------------------------------------------------------------------


@runtime_checkable
class DocumentStore(Protocol):
    """Tenant-scoped CRUD over Document/Page/Layer (spec §02)."""

    async def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        name: str,
        kind: str,
    ) -> str:
        """Create an empty document; returns its id."""
        ...

    async def get(self, document_id: str, *, tenant_id: str) -> dict[str, Any]:
        """Load a document; returns serialized state."""
        ...

    async def update(
        self,
        document_id: str,
        *,
        tenant_id: str,
        delta: dict[str, Any],
        expected_version: int | None = None,
    ) -> int:
        """Apply a delta; returns new version. Raises ConcurrentEditError on mismatch."""
        ...

    async def list_for_owner(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        archived: bool = False,
    ) -> list[dict[str, Any]]:
        """List documents owned by user within tenant."""
        ...

    async def archive(self, document_id: str, *, tenant_id: str) -> None:
        """Soft-delete (sets archived=true)."""
        ...


# ---------------------------------------------------------------------------
# Pre-flight (spec §22)
# ---------------------------------------------------------------------------


@runtime_checkable
class PreflightChecker(Protocol):
    """Run validation rules over a Document (spec §22)."""

    async def run(
        self,
        document_id: str,
        *,
        tenant_id: str,
        rule_ids: Sequence[str] | None = None,
    ) -> PreflightReport:
        """Execute all (or named) rules; returns a structured report."""
        ...

    def list_rules(self) -> tuple[str, ...]:
        """Names of all registered rules."""
        ...


@runtime_checkable
class PreflightRule(Protocol):
    """A single check rule plug-in."""

    @property
    def rule_id(self) -> str: ...

    async def check(self, document_id: str, *, tenant_id: str) -> tuple[CheckResult, ...]:
        """Run the rule; returns 0..N findings."""
        ...


# ---------------------------------------------------------------------------
# Print exporter (spec §13)
# ---------------------------------------------------------------------------


@runtime_checkable
class PrintExporter(Protocol):
    """Document → bytes in target format (spec §13)."""

    async def export(
        self,
        document_id: str,
        *,
        tenant_id: str,
        format: str,  # noqa: A002  shadows builtin; standard "format" terminology in export APIs
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Render Document to bytes; raises PreflightFailedError on FAIL."""
        ...

    def supported_formats(self) -> tuple[str, ...]:
        """E.g. ('png', 'jpg', 'webp', 'pdf', 'svg', 'epub', 'pptx')."""
        ...


# ---------------------------------------------------------------------------
# Versioning (spec §23)
# ---------------------------------------------------------------------------


@runtime_checkable
class VersionStore(Protocol):
    """Append-only DocumentVersion log + restore (spec §23)."""

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
        """Append a delta version; returns new version id."""
        ...

    async def checkpoint(
        self,
        document_id: str,
        *,
        tenant_id: str,
        author_id: str,
        message: str,
    ) -> str:
        """Create a snapshot version; returns version id."""
        ...

    async def get(
        self,
        document_id: str,
        version_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Restore the document state at the given version."""
        ...

    async def list(
        self,
        document_id: str,
        *,
        tenant_id: str,
        limit: int = 100,
        before: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """List versions, newest first."""
        ...

    async def revert(
        self,
        document_id: str,
        version_id: str,
        *,
        tenant_id: str,
        author_id: str,
    ) -> str:
        """Revert; appends a new version that branches from `version_id`."""
        ...


# ---------------------------------------------------------------------------
# Cost & budget (spec §31)
# ---------------------------------------------------------------------------


@runtime_checkable
class CostForecaster(Protocol):
    """Pre-call cost prediction (spec §31)."""

    def forecast(
        self,
        action: str,
        args: dict[str, Any],
        *,
        cache_lookup: bool = True,
    ) -> CostForecast:
        """Return forecast; deterministic for same inputs."""
        ...


@runtime_checkable
class BudgetStore(Protocol):
    """Per-scope spend tracking (spec §31)."""

    async def get_state(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
    ) -> dict[str, Any]:
        """Returns BudgetState as dict, or empty dict if unset."""
        ...

    async def reserve(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
        amount_usd: str,  # Decimal-as-str for protocol simplicity
    ) -> BudgetStatus:
        """Atomic reserve; returns OK | WARN | BLOCKED."""
        ...

    async def commit(
        self,
        scope: BudgetScope,
        scope_id: str,
        *,
        tenant_id: str,
        amount_usd: str,
    ) -> None:
        """Persist actual spend (usually equals or differs from reserve)."""
        ...

    async def upsert_budget(self, budget: Budget, *, tenant_id: str) -> None:
        """Create or update a Budget row."""
        ...


# ---------------------------------------------------------------------------
# Brand kit + assets (specs §11, §18)
# ---------------------------------------------------------------------------


@runtime_checkable
class BrandKitStore(Protocol):
    """Tenant-scoped brand kit CRUD (spec §11)."""

    async def create(self, kit: BrandKit) -> str: ...
    async def get(self, kit_id: str, *, tenant_id: str) -> BrandKit: ...
    async def list_for_tenant(self, *, tenant_id: str) -> list[BrandKit]: ...
    async def apply_to_document(self, document_id: str, kit_id: str, *, tenant_id: str) -> None: ...


@runtime_checkable
class AssetStore(Protocol):
    """Characters, props, uploads (spec §18)."""

    async def create(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        kind: str,
        name: str,
        primary_blob_id: str,
        tags: Sequence[str] = (),
    ) -> str: ...

    async def get(self, asset_id: str, *, tenant_id: str) -> dict[str, Any]: ...

    async def search(
        self,
        *,
        tenant_id: str,
        query: str = "",
        kind: str | None = None,
        tags: Sequence[str] = (),
        mode: str = "tag",
    ) -> list[dict[str, Any]]: ...

    async def archive(self, asset_id: str, *, tenant_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Corrections + critics + learnings (specs §19, §20, §30)
# ---------------------------------------------------------------------------


@runtime_checkable
class CorrectionStore(Protocol):
    """Append-only Correction event log (spec §19)."""

    async def capture(
        self,
        *,
        tenant_id: str,
        user_id: str,
        document_id: str,
        page_id: str,
        layer_id: str | None,
        session_id: str,
        kind: CorrectionKind,
        source: CorrectionSource,
        before: dict[str, Any],
        after: dict[str, Any],
        context: CorrectionContext,
    ) -> Correction:
        """Persist a correction; runs intent inference asynchronously."""
        ...

    async def list_for_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        kind: CorrectionKind | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[Correction]: ...

    async def mark_reverted(self, correction_id: str, *, tenant_id: str) -> None: ...

    async def delete_for_user(self, *, tenant_id: str, user_id: str) -> int: ...


@runtime_checkable
class CanvasLearningStore(Protocol):
    """CRUD for canvas-specific Learnings (spec §20)."""

    async def upsert(self, learning: CanvasLearning) -> None: ...

    async def list(
        self,
        *,
        tenant_id: str,
        scope: CanvasLearningScope | None = None,
        user_id: str | None = None,
        document_id: str | None = None,
        asset_id: str | None = None,
        rule_kinds: Iterable[LearningRuleKind] | None = None,
    ) -> list[CanvasLearning]: ...

    async def decay(self, *, days_since_run: int) -> int:
        """Run decay sweep; returns count of affected learnings."""
        ...

    async def pin(self, learning_id: str, *, tenant_id: str, pinned: bool) -> None: ...


@runtime_checkable
class Critic(Protocol):
    """A specialist sub-agent that promotes Learnings from Corrections (spec §30)."""

    @property
    def name(self) -> str: ...

    @property
    def watches(self) -> tuple[CorrectionKind, ...]: ...

    @property
    def precedence(self) -> int: ...

    async def aggregate(
        self,
        corrections: Sequence[Correction],
    ) -> list[CanvasLearning]:
        """Cluster + promote within this critic's domain."""
        ...


# ---------------------------------------------------------------------------
# Effects + layer rendering (spec §01)
# ---------------------------------------------------------------------------


@runtime_checkable
class EffectApplier(Protocol):
    """Apply an Effect to a raster image; backs the §01 render pipeline."""

    def supports(self, kind: EffectKind) -> bool: ...

    def apply(self, image: bytes, effect: Effect) -> bytes:
        """Apply the effect; raises EffectKindUnknownError if unsupported."""
        ...


@runtime_checkable
class LayerRenderer(Protocol):
    """Compose a Layer with its source + effects + mask + blend (spec §01)."""

    def render(self, layer: dict[str, Any]) -> bytes:
        """Render a layer dict (transport-friendly form) → composited PNG bytes."""
        ...


# ---------------------------------------------------------------------------
# Manuscript + localization + audio (specs §33, §26, §27)
# ---------------------------------------------------------------------------


@runtime_checkable
class ManuscriptImporter(Protocol):
    """Parse + paginate a manuscript into a Document (spec §33)."""

    async def import_(
        self,
        file_bytes: bytes,
        format: str,  # noqa: A002  shadows builtin; "format" is standard import API terminology
        *,
        doc_kind: str,
        age_band: str,
        tenant_id: str,
        owner_id: str,
        layout_kind: str | None = None,
        language: str = "en",
    ) -> str:
        """Parse + paginate; returns new document_id."""
        ...


@runtime_checkable
class TranslationBackend(Protocol):
    """LLM-driven translation per text layer (spec §26)."""

    async def translate(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        age_band: str | None = None,
    ) -> str: ...


@runtime_checkable
class TTSBackend(Protocol):
    """Text-to-speech (spec §27)."""

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str,
        language: str = "en",
    ) -> bytes:
        """Returns audio bytes (provider's native format; usually mp3 or wav)."""
        ...

    async def list_voices(self, *, language: str | None = None) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# LoRA / fine-tuning (spec §21)
# ---------------------------------------------------------------------------


@runtime_checkable
class LoraTrainerBackend(Protocol):
    """Submit + poll fine-tuning jobs (spec §21)."""

    async def submit(
        self,
        *,
        tenant_id: str,
        scope: str,
        scope_id: str,
        base_model: str,
        training_blob_ids: Sequence[str],
        metadata_jsonl: bytes,
    ) -> str:
        """Submit a job; returns provider job_id."""
        ...

    async def status(self, job_id: str) -> dict[str, Any]:
        """Poll job; returns status, progress, result_blob_id when done."""
        ...

    async def cancel(self, job_id: str) -> None: ...


# ---------------------------------------------------------------------------
# Embeddings (spec §18)
# ---------------------------------------------------------------------------


@runtime_checkable
class ImageEmbedder(Protocol):
    """CLIP-style image embedding (spec §18)."""

    async def embed(self, image: bytes) -> tuple[float, ...]:
        """Returns a fixed-dim vector (e.g. 512 for ViT-B/32)."""
        ...
