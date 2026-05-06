"""Style lock store + drift scorer + palette extraction (spec §09).

In-process implementation:
  - `PillowPaletteExtractor` extracts a small dominant-colour palette from
    an RGBA image via Pillow's median-cut quantisation (no numpy dep).
  - `MockStyleDescriber` returns a placeholder description (a real
    deployment swaps in a vision-LLM via the StyleLockChecker Protocol).
  - `MockDriftScorer` computes drift via palette ΔE — same image vs lock
    palette → near-zero; very different palette → near-one. Production
    swaps in the vision-LLM scorer.
  - `InMemoryStyleLockStore` is the tenant-scoped CRUD + apply layer.
  - `prompt_suffix(lock)` is the helper §04/§09 inject at gen time.
"""

from __future__ import annotations

import dataclasses
import io
import math
import uuid
from typing import TYPE_CHECKING

from PIL import Image

from stronghold.types.canvas_design import (
    Color,
    LightingDirection,
    LineWeight,
    MoodTag,
    StyleDriftScore,
    StyleLock,
)
from stronghold.types.errors import (
    StyleDriftCheckUnavailableError,
    StyleLockApplyConflictError,
    StyleLockNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------------------
# Palette extraction
# ---------------------------------------------------------------------------


class PillowPaletteExtractor:
    """Median-cut palette extractor satisfying StyleLockChecker.extract_palette."""

    async def extract_palette(
        self,
        image_bytes: bytes,
        *,
        k: int = 5,
    ) -> tuple[str, ...]:
        if not 3 <= k <= 7:
            # StyleLock accepts 3..7; anything outside that range is a
            # caller bug (palette wouldn't fit a valid lock).
            raise StyleDriftCheckUnavailableError(f"palette size k must be in [3, 7], got {k}")
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        # quantize() returns a P-mode image with a palette of `k` colours
        quant = img.quantize(colors=k, method=Image.Quantize.MEDIANCUT)
        palette = quant.getpalette() or []
        # palette is a flat [r, g, b, r, g, b, ...] list. Pillow may return
        # fewer than k entries on near-solid images — pad by repeating the
        # last entry so callers always get exactly k.
        actual_count = len(palette) // 3
        out: list[str] = []
        for i in range(k):
            idx = min(i, actual_count - 1) if actual_count > 0 else 0
            if actual_count == 0:
                # Defensive: Pillow returned no palette at all
                out.append("#000000")
                continue
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            out.append(f"#{r:02X}{g:02X}{b:02X}")
        return tuple(out)


# ---------------------------------------------------------------------------
# Drift scorer
# ---------------------------------------------------------------------------


class MockDriftScorer:
    """In-process drift scorer using palette ΔE.

    `score(layer_bytes, lock)` returns a value in [0, 1] — 0 means the
    layer's dominant palette matches the lock; 1 means it's wildly off.

    Production swaps this for a vision-LLM scorer that also accounts for
    rendering style, line weight, lighting. The Mock is deterministic
    and cheap enough for unit tests + dev loops.
    """

    def __init__(self, *, extractor: PillowPaletteExtractor | None = None) -> None:
        self._extractor = extractor or PillowPaletteExtractor()

    async def score(
        self,
        layer_bytes: bytes,
        lock: StyleLock,
    ) -> float:
        layer_palette = await self._extractor.extract_palette(layer_bytes, k=len(lock.palette))
        return _palette_delta(layer_palette, tuple(c.value for c in lock.palette))

    async def describe(self, image_bytes: bytes) -> str:
        # Mock: report the dominant palette as a "description". A real
        # implementation queries a vision LLM.
        palette = await self._extractor.extract_palette(image_bytes, k=5)
        return f"palette={palette}"


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class InMemoryStyleLockStore:
    """Tenant-scoped style-lock CRUD with version history (spec §09)."""

    def __init__(self) -> None:
        # tenant_id → lock_id → list[StyleLock] (history; latest at end)
        self._history: dict[str, dict[str, list[StyleLock]]] = {}
        # tenant_id → name → lock_id (for `load_by_name`)
        self._by_name: dict[str, dict[str, str]] = {}

    # ── lifecycle ──────────────────────────────────────────────────────

    async def create_from_brief(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        name: str,
        rendering_style_prompt: str,
        palette: Sequence[Color],
        line_weight: LineWeight = LineWeight.MEDIUM,
        lighting: LightingDirection = LightingDirection.NATURAL,
        mood: MoodTag = MoodTag.PLAYFUL,
        document_id: str | None = None,
        drift_threshold: float = 0.25,
    ) -> StyleLock:
        lock_id = _new_id()
        lock = StyleLock(
            id=lock_id,
            tenant_id=tenant_id,
            owner_id=owner_id,
            name=name,
            rendering_style_prompt=rendering_style_prompt,
            palette=tuple(palette),
            line_weight=line_weight,
            lighting=lighting,
            mood=mood,
            document_id=document_id,
            drift_threshold=drift_threshold,
            reference_palette_extracted=False,
        )
        self._save(lock)
        return lock

    async def create_from_image(
        self,
        *,
        tenant_id: str,
        owner_id: str,
        name: str,
        image_bytes: bytes,
        reference_image_blob_id: str | None = None,
        line_weight: LineWeight = LineWeight.MEDIUM,
        lighting: LightingDirection = LightingDirection.NATURAL,
        mood: MoodTag = MoodTag.PLAYFUL,
        document_id: str | None = None,
        drift_threshold: float = 0.25,
        extractor: PillowPaletteExtractor | None = None,
        describer: MockDriftScorer | None = None,
    ) -> StyleLock:
        ext = extractor or PillowPaletteExtractor()
        palette = await ext.extract_palette(image_bytes, k=5)
        desc_obj = describer or MockDriftScorer(extractor=ext)
        description = await desc_obj.describe(image_bytes)
        lock = StyleLock(
            id=_new_id(),
            tenant_id=tenant_id,
            owner_id=owner_id,
            name=name,
            rendering_style_prompt=description,
            palette=tuple(Color(p) for p in palette),
            line_weight=line_weight,
            lighting=lighting,
            mood=mood,
            document_id=document_id,
            reference_image_blob_id=reference_image_blob_id,
            reference_palette_extracted=True,
            drift_threshold=drift_threshold,
        )
        self._save(lock)
        return lock

    async def refine(
        self,
        lock_id: str,
        *,
        tenant_id: str,
        rendering_style_prompt: str | None = None,
        palette: Sequence[Color] | None = None,
        line_weight: LineWeight | None = None,
        lighting: LightingDirection | None = None,
        mood: MoodTag | None = None,
        drift_threshold: float | None = None,
        lora_id: str | None = None,
    ) -> StyleLock:
        prior = await self.get(lock_id, tenant_id=tenant_id)
        new_lock = dataclasses.replace(
            prior,
            version=prior.version + 1,
            rendering_style_prompt=(
                rendering_style_prompt
                if rendering_style_prompt is not None
                else prior.rendering_style_prompt
            ),
            palette=tuple(palette) if palette is not None else prior.palette,
            line_weight=line_weight if line_weight is not None else prior.line_weight,
            lighting=lighting if lighting is not None else prior.lighting,
            mood=mood if mood is not None else prior.mood,
            drift_threshold=(
                drift_threshold if drift_threshold is not None else prior.drift_threshold
            ),
            lora_id=lora_id if lora_id is not None else prior.lora_id,
        )
        self._save(new_lock)
        return new_lock

    # ── reads ──────────────────────────────────────────────────────────

    async def get(self, lock_id: str, *, tenant_id: str) -> StyleLock:
        bucket = self._history.get(tenant_id, {})
        history = bucket.get(lock_id)
        if not history:
            raise StyleLockNotFoundError(f"style lock {lock_id!r} not found")
        return history[-1]

    async def get_history(self, lock_id: str, *, tenant_id: str) -> tuple[StyleLock, ...]:
        bucket = self._history.get(tenant_id, {})
        history = bucket.get(lock_id)
        if not history:
            raise StyleLockNotFoundError(f"style lock {lock_id!r} not found")
        return tuple(history)

    async def load_by_name(self, name: str, *, tenant_id: str) -> StyleLock:
        names = self._by_name.get(tenant_id, {})
        lock_id = names.get(name)
        if lock_id is None:
            raise StyleLockNotFoundError(f"no style lock named {name!r}")
        return await self.get(lock_id, tenant_id=tenant_id)

    async def list(self, *, tenant_id: str) -> list[StyleLock]:
        bucket = self._history.get(tenant_id, {})
        return [history[-1] for history in bucket.values() if history]

    # ── application ────────────────────────────────────────────────────

    async def apply_to_document(
        self,
        document_id: str,
        lock_id: str,
        *,
        tenant_id: str,
        replace: bool = False,
        document_store: object | None = None,
    ) -> StyleLock:
        """Apply lock to a document via injected DocumentStore.

        `replace=True` allows overriding an existing lock. If the document
        already references a different lock and `replace=False`, raise
        StyleLockApplyConflictError.
        """
        lock = await self.get(lock_id, tenant_id=tenant_id)
        if document_store is not None:
            doc_dict = await document_store.get(document_id, tenant_id=tenant_id)  # type: ignore[attr-defined]
            existing = doc_dict.get("style_lock_id")
            if existing and existing != lock_id and not replace:
                raise StyleLockApplyConflictError(
                    f"document {document_id} already has lock {existing}"
                )
            await document_store.update(  # type: ignore[attr-defined]
                document_id,
                tenant_id=tenant_id,
                delta={"style_lock_id": lock_id},
            )
        return lock

    # ── helpers ────────────────────────────────────────────────────────

    def _save(self, lock: StyleLock) -> None:
        bucket = self._history.setdefault(lock.tenant_id, {})
        bucket.setdefault(lock.id, []).append(lock)
        names = self._by_name.setdefault(lock.tenant_id, {})
        names[lock.name] = lock.id


# ---------------------------------------------------------------------------
# Drift checking + preflight integration
# ---------------------------------------------------------------------------


async def style_lock_check_layer(
    layer_id: str,
    page_id: str,
    layer_bytes: bytes,
    lock: StyleLock,
    *,
    scorer: MockDriftScorer | None = None,
) -> StyleDriftScore:
    """Compute a StyleDriftScore for one layer against a lock."""
    s = scorer or MockDriftScorer()
    score = await s.score(layer_bytes, lock)
    return StyleDriftScore(
        layer_id=layer_id,
        page_id=page_id,
        lock_id=lock.id,
        lock_version=lock.version,
        score=score,
        components={"palette": score},
        reasoning="palette ΔE (mock; production uses vision-LLM)",
    )


# ---------------------------------------------------------------------------
# Prompt suffix injection (used by §04 generative)
# ---------------------------------------------------------------------------


def prompt_suffix(lock: StyleLock) -> str:
    """Build the prompt suffix appended to every generation under this lock."""
    palette = ", ".join(c.value for c in lock.palette[:3])
    parts = [
        f"in {lock.rendering_style_prompt} style" if lock.rendering_style_prompt else "",
        f"using palette of {palette}" if palette else "",
        f"with {lock.line_weight.value} line work" if lock.line_weight else "",
        f"{lock.lighting.value} lighting"
        if lock.lighting and lock.lighting is not LightingDirection.NONE
        else "",
    ]
    return ", ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _delta_e(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """CIE76-ish ΔE in RGB space (cheap; not perceptually accurate but
    monotone enough for drift heuristics)."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _palette_delta(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Mean nearest-neighbour ΔE between two palettes, normalised to [0, 1]."""
    if not a or not b:
        return 1.0
    a_rgb = [_hex_to_rgb(c) for c in a]
    b_rgb = [_hex_to_rgb(c) for c in b]
    total = 0.0
    for ca in a_rgb:
        nearest = min(_delta_e(ca, cb) for cb in b_rgb)
        total += nearest
    avg = total / len(a_rgb)
    # ΔE in RGB has max ~441 (sqrt(3) * 255). Normalise.
    return min(1.0, avg / 441.673)
