"""Style lock green tests — features/style-lock.feature scenarios."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from stronghold.persistence.canvas_design_memory import InMemoryDocumentStore
from stronghold.tools.canvas_preflight import (
    PreflightChecker,
    StyleLockDriftRule,
)
from stronghold.tools.canvas_style_lock import (
    InMemoryStyleLockStore,
    MockDriftScorer,
    PillowPaletteExtractor,
    prompt_suffix,
    style_lock_check_layer,
)
from stronghold.types.canvas_design import (
    Color,
    Document,
    DocumentKind,
    Layer,
    LightingDirection,
    LineWeight,
    MoodTag,
    Page,
    PrintSpec,
    RasterSource,
    ReportLevel,
    StyleLock,
)
from stronghold.types.errors import (
    StyleLockApplyConflictError,
    StyleLockNotFoundError,
)

# ─── Fixtures ──────────────────────────────────────────────────────────────


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", (width, height), color=rgb)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _multicolour_png() -> bytes:
    """5-band image with 5 distinct dominant colours."""
    img = Image.new("RGB", (50, 50), (255, 0, 0))  # red default
    pixels = img.load()
    assert pixels is not None
    bands = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (255, 0, 255),
    ]
    for y in range(50):
        band = bands[y // 10]
        for x in range(50):
            pixels[x, y] = band
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def store() -> InMemoryStyleLockStore:
    return InMemoryStyleLockStore()


@pytest.fixture
def extractor() -> PillowPaletteExtractor:
    return PillowPaletteExtractor()


# ─── Palette extraction ────────────────────────────────────────────────────


class TestPaletteExtraction:
    async def test_extracts_5_colour_palette(self, extractor: PillowPaletteExtractor) -> None:
        palette = await extractor.extract_palette(_multicolour_png(), k=5)
        assert len(palette) == 5
        for entry in palette:
            assert entry.startswith("#")
            assert len(entry) == 7

    async def test_solid_image_extracts_repeated_colour(
        self, extractor: PillowPaletteExtractor
    ) -> None:
        palette = await extractor.extract_palette(_png(20, 20, (200, 100, 50)), k=3)
        # Mediancut on a solid image produces three identical entries
        assert len(set(palette)) == 1

    async def test_extract_returns_valid_hex(self, extractor: PillowPaletteExtractor) -> None:
        palette = await extractor.extract_palette(_multicolour_png(), k=3)
        # All entries valid Color (uppercase hex)
        for hex_str in palette:
            Color(hex_str)


# ─── Style lock creation ───────────────────────────────────────────────────


class TestCreateFromBrief:
    async def test_create_with_brief_fields_preserved(self, store: InMemoryStyleLockStore) -> None:
        lock = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="warrior-knight",
            rendering_style_prompt="watercolour, soft, warm",
            palette=tuple(
                Color(c) for c in ("#FFAA00", "#FF0044", "#3344CC", "#22BB55", "#AA66FF")
            ),
            line_weight=LineWeight.FINE,
            lighting=LightingDirection.DRAMATIC,
            mood=MoodTag.EPIC,
        )
        assert lock.rendering_style_prompt == "watercolour, soft, warm"
        assert lock.line_weight is LineWeight.FINE
        assert lock.lighting is LightingDirection.DRAMATIC
        assert lock.mood is MoodTag.EPIC
        assert len(lock.palette) == 5
        assert lock.reference_palette_extracted is False
        assert lock.version == 1


class TestCreateFromImage:
    async def test_create_from_image_extracts_palette(self, store: InMemoryStyleLockStore) -> None:
        lock = await store.create_from_image(
            tenant_id="acme",
            owner_id="alice",
            name="extracted",
            image_bytes=_multicolour_png(),
        )
        assert len(lock.palette) == 5
        assert lock.reference_palette_extracted is True
        # The mock describer reports a palette in the prompt
        assert "palette=" in lock.rendering_style_prompt


# ─── Refinement ────────────────────────────────────────────────────────────


class TestRefine:
    async def test_refine_bumps_version(self, store: InMemoryStyleLockStore) -> None:
        original = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="warrior",
            rendering_style_prompt="watercolour",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        refined = await store.refine(
            original.id,
            tenant_id="acme",
            rendering_style_prompt="watercolour, dark mood",
        )
        assert refined.version == 2
        assert refined.rendering_style_prompt == "watercolour, dark mood"

    async def test_refine_preserves_prior_in_history(self, store: InMemoryStyleLockStore) -> None:
        original = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="x",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        await store.refine(original.id, tenant_id="acme", lighting=LightingDirection.RIM)
        history = await store.get_history(original.id, tenant_id="acme")
        assert len(history) == 2
        assert history[0].version == 1
        assert history[1].version == 2

    async def test_get_returns_latest(self, store: InMemoryStyleLockStore) -> None:
        lock = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="x",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        await store.refine(lock.id, tenant_id="acme", mood=MoodTag.QUIET)
        latest = await store.get(lock.id, tenant_id="acme")
        assert latest.version == 2
        assert latest.mood is MoodTag.QUIET


# ─── Drift scoring ─────────────────────────────────────────────────────────


class TestDriftScore:
    async def test_identical_palette_scores_low(self, store: InMemoryStyleLockStore) -> None:
        red = _png(50, 50, (255, 0, 0))
        lock = await store.create_from_image(
            tenant_id="acme",
            owner_id="alice",
            name="red-lock",
            image_bytes=red,
        )
        result = await style_lock_check_layer(
            "L1",
            "P0",
            red,
            lock,
        )
        assert result.score < 0.05

    async def test_distant_palette_scores_high(self, store: InMemoryStyleLockStore) -> None:
        red = _png(50, 50, (255, 0, 0))
        green = _png(50, 50, (0, 255, 0))
        lock = await store.create_from_image(
            tenant_id="acme",
            owner_id="alice",
            name="red-lock",
            image_bytes=red,
        )
        result = await style_lock_check_layer(
            "L1",
            "P0",
            green,
            lock,
        )
        assert result.score > 0.4

    async def test_drift_score_components_set(self, store: InMemoryStyleLockStore) -> None:
        red = _png(50, 50, (255, 0, 0))
        lock = await store.create_from_image(
            tenant_id="acme",
            owner_id="alice",
            name="red-lock",
            image_bytes=red,
        )
        result = await style_lock_check_layer("L1", "P0", red, lock)
        assert "palette" in result.components

    async def test_drift_score_validation(self) -> None:
        from stronghold.types.canvas_design import StyleDriftScore
        from stronghold.types.errors import ConfigError

        with pytest.raises(ConfigError):
            StyleDriftScore(
                layer_id="L",
                page_id="P",
                lock_id="lock",
                lock_version=1,
                score=1.5,
            )


# ─── Apply ─────────────────────────────────────────────────────────────────


def _make_doc(doc_store: InMemoryDocumentStore) -> str:
    import asyncio

    return asyncio.run(
        doc_store.create(tenant_id="acme", owner_id="alice", name="B", kind="picture_book")
    )


class TestApplyToDocument:
    async def test_applies_lock_id_to_document(self, store: InMemoryStyleLockStore) -> None:
        doc_store = InMemoryDocumentStore()
        doc_id = await doc_store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        lock = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="x",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        await store.apply_to_document(doc_id, lock.id, tenant_id="acme", document_store=doc_store)
        doc_dict = await doc_store.get(doc_id, tenant_id="acme")
        assert doc_dict["style_lock_id"] == lock.id

    async def test_apply_conflict_without_replace_raises(
        self, store: InMemoryStyleLockStore
    ) -> None:
        doc_store = InMemoryDocumentStore()
        doc_id = await doc_store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        lock_a = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="a",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        lock_b = await store.create_from_brief(
            tenant_id="acme",
            owner_id="alice",
            name="b",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        await store.apply_to_document(doc_id, lock_a.id, tenant_id="acme", document_store=doc_store)
        with pytest.raises(StyleLockApplyConflictError):
            await store.apply_to_document(
                doc_id, lock_b.id, tenant_id="acme", document_store=doc_store
            )
        # replace=True succeeds
        await store.apply_to_document(
            doc_id, lock_b.id, tenant_id="acme", replace=True, document_store=doc_store
        )


# ─── Tenant isolation ──────────────────────────────────────────────────────


class TestTenantIsolation:
    async def test_cross_tenant_get_raises(self, store: InMemoryStyleLockStore) -> None:
        lock = await store.create_from_brief(
            tenant_id="globex",
            owner_id="bob",
            name="x",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        with pytest.raises(StyleLockNotFoundError):
            await store.get(lock.id, tenant_id="acme")

    async def test_load_by_name_tenant_scoped(self, store: InMemoryStyleLockStore) -> None:
        await store.create_from_brief(
            tenant_id="globex",
            owner_id="bob",
            name="warrior",
            rendering_style_prompt="r",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
        )
        with pytest.raises(StyleLockNotFoundError):
            await store.load_by_name("warrior", tenant_id="acme")


# ─── Prompt suffix injection ───────────────────────────────────────────────


class TestPromptSuffix:
    def test_suffix_includes_style_palette_line_lighting(self) -> None:
        lock = StyleLock(
            id="x",
            tenant_id="t",
            owner_id="u",
            name="x",
            rendering_style_prompt="watercolour, soft",
            palette=(Color("#FFAA00"), Color("#FF0044"), Color("#3344CC")),
            line_weight=LineWeight.FINE,
            lighting=LightingDirection.DRAMATIC,
        )
        suffix = prompt_suffix(lock)
        assert "watercolour, soft" in suffix
        assert "#FFAA00" in suffix
        assert "fine" in suffix
        assert "dramatic" in suffix

    def test_suffix_omits_none_lighting(self) -> None:
        lock = StyleLock(
            id="x",
            tenant_id="t",
            owner_id="u",
            name="x",
            rendering_style_prompt="r",
            palette=(Color("#FFAA00"), Color("#FF0044"), Color("#3344CC")),
            lighting=LightingDirection.NONE,
        )
        suffix = prompt_suffix(lock)
        assert "lighting" not in suffix


# ─── Pre-flight integration ────────────────────────────────────────────────


class TestPreflightDriftRule:
    async def test_drift_above_threshold_warns(self) -> None:
        spec = PrintSpec(trim_size=(200, 200), bleed=10, safe_area=20)
        layer = Layer(
            id="L1",
            name="art",
            source=RasterSource(blob_id="b", width=10, height=10),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(layer,))
        doc = Document(
            id="D1",
            tenant_id="acme",
            owner_id="alice",
            name="B",
            kind=DocumentKind.PICTURE_BOOK,
            pages=(page,),
        )
        rule = StyleLockDriftRule(scores={"L1": 0.6}, threshold=0.25)
        checker = PreflightChecker(rules=(rule,))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.warnings == 1
        assert report.level is ReportLevel.WARN

    async def test_drift_below_threshold_passes(self) -> None:
        spec = PrintSpec(trim_size=(200, 200), bleed=10, safe_area=20)
        layer = Layer(
            id="L1",
            name="art",
            source=RasterSource(blob_id="b", width=10, height=10),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(layer,))
        doc = Document(
            id="D1",
            tenant_id="acme",
            owner_id="alice",
            name="B",
            kind=DocumentKind.PICTURE_BOOK,
            pages=(page,),
        )
        rule = StyleLockDriftRule(scores={"L1": 0.1}, threshold=0.25)
        checker = PreflightChecker(rules=(rule,))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.warnings == 0


# ─── Drift scorer protocol conformance ─────────────────────────────────────


class TestProtocolConformance:
    def test_pillow_palette_extractor_basics(self) -> None:
        # Minimal smoke — the StyleLockChecker Protocol covers
        # extract_palette + describe + score; our extractor handles palette,
        # the MockDriftScorer covers describe + score.
        ext = PillowPaletteExtractor()
        assert callable(ext.extract_palette)

    def test_mock_drift_scorer_satisfies_describe_and_score(self) -> None:
        scorer = MockDriftScorer()
        assert callable(scorer.score)
        assert callable(scorer.describe)
