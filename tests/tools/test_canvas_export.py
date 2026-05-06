"""Export pipeline green tests — features/export.feature scenarios."""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image

from stronghold.tools.canvas_effects import PillowEffectApplier
from stronghold.tools.canvas_export import (
    ExportOptions,
    LayerCompositor,
    PrintExporter,
)
from stronghold.tools.canvas_preflight import PreflightChecker
from stronghold.types.canvas_design import (
    BlendMode,
    Color,
    Document,
    DocumentKind,
    Effect,
    EffectKind,
    Layer,
    LayerTransform,
    Page,
    PrintSpec,
    RasterSource,
    ShapeKind,
    ShapeSource,
    ShapeStroke,
    TextSource,
)
from stronghold.types.errors import (
    EmptyDocumentError,
    ExportFormatUnsupportedError,
    PreflightFailedError,
)

# ─── Fixtures ──────────────────────────────────────────────────────────────


def _rgba(canvas: Image.Image, x: int, y: int) -> tuple[int, int, int, int]:
    """Type-tightened wrapper for canvas.getpixel — always RGBA 4-tuple."""
    px = canvas.getpixel((x, y))
    assert isinstance(px, tuple) and len(px) == 4
    return (int(px[0]), int(px[1]), int(px[2]), int(px[3]))


def _png(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    img = Image.new("RGBA", (width, height), color=rgba)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _spec() -> PrintSpec:
    return PrintSpec(trim_size=(200, 200), bleed=10, safe_area=20)


def _bg_layer(
    width: int, height: int, *, color: tuple[int, int, int, int] = (255, 0, 0, 255)
) -> Layer:
    return Layer(
        id="bg",
        name="bg",
        source=RasterSource(
            blob_id="b", width=width, height=height, inline_bytes=_png(width, height, color)
        ),
    )


def _page(page_id: str, ordering: int, *, layers: tuple[Layer, ...] | None = None) -> Page:
    spec = _spec()
    bw, bh = spec.bleed_canvas
    if layers is None:
        layers = (_bg_layer(bw, bh),)
    return Page(id=page_id, ordering=ordering, print_spec=spec, layers=layers)


def _doc(*, pages: tuple[Page, ...]) -> Document:
    return Document(
        id="D1",
        tenant_id="acme",
        owner_id="alice",
        name="Book",
        kind=DocumentKind.PICTURE_BOOK,
        pages=pages,
    )


# ─── PNG export ────────────────────────────────────────────────────────────


class TestPngExport:
    async def test_single_page_returns_valid_png(self) -> None:
        doc = _doc(pages=(_page("P0", 0),))
        exporter = PrintExporter()
        out = await exporter.export_document(doc, format="png")
        # Identifies as PNG
        img = Image.open(io.BytesIO(out))
        img.verify()
        # Re-open after verify to check dims
        img = Image.open(io.BytesIO(out))
        assert img.format == "PNG"
        assert img.size == _spec().bleed_canvas

    async def test_multi_page_returns_zip(self) -> None:
        doc = _doc(pages=(_page("P0", 0), _page("P1", 1), _page("P2", 2)))
        exporter = PrintExporter()
        out = await exporter.export_document(doc, format="png")
        # Multi-page → ZIP container
        zf = zipfile.ZipFile(io.BytesIO(out))
        names = zf.namelist()
        assert len(names) == 3
        assert all(n.endswith(".png") for n in names)


class TestJpgExport:
    async def test_single_page_jpg(self) -> None:
        doc = _doc(pages=(_page("P0", 0),))
        exporter = PrintExporter()
        out = await exporter.export_document(doc, format="jpg")
        img = Image.open(io.BytesIO(out))
        assert img.format == "JPEG"

    async def test_jpg_quality_setting(self) -> None:
        doc = _doc(pages=(_page("P0", 0),))
        exporter = PrintExporter()
        low = await exporter.export_document(doc, format="jpg", options=ExportOptions(quality=20))
        high = await exporter.export_document(doc, format="jpg", options=ExportOptions(quality=95))
        # Higher quality produces larger files for the same input
        assert len(high) >= len(low)


class TestWebpExport:
    async def test_single_page_webp(self) -> None:
        doc = _doc(pages=(_page("P0", 0),))
        exporter = PrintExporter()
        out = await exporter.export_document(doc, format="webp")
        img = Image.open(io.BytesIO(out))
        assert img.format == "WEBP"


class TestPdfExport:
    async def test_single_page_pdf_starts_with_header(self) -> None:
        doc = _doc(pages=(_page("P0", 0),))
        exporter = PrintExporter()
        out = await exporter.export_document(doc, format="pdf")
        assert out.startswith(b"%PDF-")

    async def test_multi_page_pdf_combines_pages(self) -> None:
        doc = _doc(pages=(_page("P0", 0), _page("P1", 1), _page("P2", 2)))
        exporter = PrintExporter()
        out = await exporter.export_document(doc, format="pdf")
        # A multi-page PDF is meaningfully larger than a single-page export
        single = await exporter.export_document(_doc(pages=(_page("P0", 0),)), format="pdf")
        assert len(out) > len(single)


# ─── Pre-flight gate ───────────────────────────────────────────────────────


class TestPreflightGate:
    async def test_pre_flight_failure_blocks_export_by_default(self) -> None:
        # Build a doc with bg that does NOT cover bleed → preflight FAILs
        spec = _spec()
        too_small_bg = Layer(
            id="bg",
            name="bg",
            source=RasterSource(
                blob_id="b", width=10, height=10, inline_bytes=_png(10, 10, (0, 0, 0, 255))
            ),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(too_small_bg,))
        doc = _doc(pages=(page,))
        exporter = PrintExporter(preflight_runner=PreflightChecker())
        with pytest.raises(PreflightFailedError):
            await exporter.export_document(doc, format="png")

    async def test_pre_flight_bypass_with_ignore_preflight(self) -> None:
        spec = _spec()
        too_small_bg = Layer(
            id="bg",
            name="bg",
            source=RasterSource(
                blob_id="b", width=10, height=10, inline_bytes=_png(10, 10, (0, 0, 0, 255))
            ),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(too_small_bg,))
        doc = _doc(pages=(page,))
        exporter = PrintExporter(preflight_runner=PreflightChecker())
        out = await exporter.export_document(
            doc, format="png", options=ExportOptions(ignore_preflight=True)
        )
        # Got valid PNG bytes despite the FAIL
        Image.open(io.BytesIO(out)).verify()


# ─── Empty + format errors ─────────────────────────────────────────────────


class TestErrors:
    async def test_empty_document_raises(self) -> None:
        doc = _doc(pages=())  # would hit Document validator? No — gapless 0..N empty is OK
        exporter = PrintExporter()
        with pytest.raises(EmptyDocumentError):
            await exporter.export_document(doc, format="png")

    async def test_unsupported_format_raises(self) -> None:
        doc = _doc(pages=(_page("P0", 0),))
        exporter = PrintExporter()
        with pytest.raises(ExportFormatUnsupportedError):
            await exporter.export_document(doc, format="bmp")


# ─── Page range option ─────────────────────────────────────────────────────


class TestPageRange:
    async def test_page_range_filters_to_subset(self) -> None:
        doc = _doc(pages=(_page("P0", 0), _page("P1", 1), _page("P2", 2), _page("P3", 3)))
        exporter = PrintExporter()
        out = await exporter.export_document(
            doc, format="png", options=ExportOptions(page_range=(1, 2))
        )
        zf = zipfile.ZipFile(io.BytesIO(out))
        # 2 pages selected → ZIP with 2 entries
        assert len(zf.namelist()) == 2


# ─── LayerCompositor specifics ─────────────────────────────────────────────


class TestLayerCompositor:
    def test_invisible_layer_not_rendered(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        red = _bg_layer(bw, bh, color=(255, 0, 0, 255))
        invisible_blue = Layer(
            id="blue",
            name="blue",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (0, 0, 255, 255))
            ),
            visible=False,
            z_index=10,
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(red, invisible_blue))
        canvas = LayerCompositor().compose(page)
        # Centre pixel should still be red, not blue
        cx, cy = canvas.size[0] // 2, canvas.size[1] // 2
        assert _rgba(canvas, cx, cy)[:3] == (255, 0, 0)

    def test_z_index_orders_layers_back_to_front(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        red = Layer(
            id="r",
            name="r",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (255, 0, 0, 255))
            ),
            z_index=0,
        )
        blue = Layer(
            id="b",
            name="b",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (0, 0, 255, 255))
            ),
            z_index=1,
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(red, blue))
        canvas = LayerCompositor().compose(page)
        cx, cy = canvas.size[0] // 2, canvas.size[1] // 2
        # blue (z=1) on top of red (z=0)
        assert _rgba(canvas, cx, cy)[:3] == (0, 0, 255)

    def test_opacity_blends_with_background(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        red = Layer(
            id="r",
            name="r",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (255, 0, 0, 255))
            ),
            z_index=0,
        )
        # 50%-opacity blue over red
        blue_half = Layer(
            id="b",
            name="b",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (0, 0, 255, 255))
            ),
            z_index=1,
            opacity=0.5,
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(red, blue_half))
        canvas = LayerCompositor().compose(page)
        cx, cy = canvas.size[0] // 2, canvas.size[1] // 2
        r, g, b, _a = _rgba(canvas, cx, cy)
        # 50/50 blend → roughly equal channels
        assert 100 < r < 200
        assert 100 < b < 200
        assert g < 30

    def test_text_layer_renders_glyphs(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        bg = _bg_layer(bw, bh, color=(255, 255, 255, 255))
        text = Layer(
            id="t",
            name="t",
            source=TextSource(content="Hi"),
            transform=LayerTransform(x=10, y=10),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(bg, text))
        canvas = LayerCompositor().compose(page)
        # Some pixel inside the text area should not be pure white
        any_dark = False
        for x in range(10, 40):
            for y in range(10, 30):
                if _rgba(canvas, x, y)[:3] != (255, 255, 255):
                    any_dark = True
                    break
            if any_dark:
                break
        assert any_dark, "expected text glyphs to render dark pixels over white bg"

    def test_shape_rectangle_renders(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        bg = _bg_layer(bw, bh, color=(255, 255, 255, 255))
        rect = Layer(
            id="r",
            name="r",
            source=ShapeSource(
                shape_kind=ShapeKind.RECTANGLE,
                geometry={"width": 30, "height": 30},
                fill={"kind": "solid", "color": Color("#00FF00")},
                stroke=ShapeStroke(color=Color("#000000"), width=1.0),
            ),
            transform=LayerTransform(x=20, y=20),
            z_index=1,
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(bg, rect))
        canvas = LayerCompositor().compose(page)
        # Rectangle interior is green
        assert _rgba(canvas, 30, 30)[:3] == (0, 255, 0)

    def test_shape_unsupported_kind_skipped(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        bg = _bg_layer(bw, bh, color=(255, 0, 0, 255))
        star = Layer(
            id="s",
            name="s",
            source=ShapeSource(
                shape_kind=ShapeKind.STAR,
                geometry={"width": 30, "height": 30, "points": 5},
            ),
            z_index=1,
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(bg, star))
        # Should not raise; bg renders unchanged
        canvas = LayerCompositor().compose(page)
        cx, cy = canvas.size[0] // 2, canvas.size[1] // 2
        assert _rgba(canvas, cx, cy)[:3] == (255, 0, 0)

    def test_effects_threaded_through_when_applier_set(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        bg = Layer(
            id="bg",
            name="bg",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (200, 200, 200, 255))
            ),
            effects=(Effect(id="i", kind=EffectKind.INVERT, params={}),),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(bg,))
        canvas = LayerCompositor(applier=PillowEffectApplier()).compose(page)
        cx, cy = canvas.size[0] // 2, canvas.size[1] // 2
        # 200 inverted → 55
        r, g, b, _a = _rgba(canvas, cx, cy)
        assert 50 <= r <= 60

    def test_blend_mode_multiply(self) -> None:
        spec = _spec()
        bw, bh = spec.bleed_canvas
        red = Layer(
            id="r",
            name="r",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (255, 100, 100, 255))
            ),
            z_index=0,
        )
        gray = Layer(
            id="g",
            name="g",
            source=RasterSource(
                blob_id="b", width=bw, height=bh, inline_bytes=_png(bw, bh, (128, 128, 128, 255))
            ),
            z_index=1,
            blend_mode=BlendMode.MULTIPLY,
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(red, gray))
        canvas = LayerCompositor().compose(page)
        cx, cy = canvas.size[0] // 2, canvas.size[1] // 2
        r, g, b, _a = _rgba(canvas, cx, cy)
        # MULTIPLY 255 * 128 / 255 = 128 (channel-wise); 100 * 128 / 255 ≈ 50
        assert 110 < r < 140
        assert 30 < g < 70

    def test_oversized_canvas_raises(self) -> None:
        # Force absurd dims via a custom PrintSpec (no public way to bypass
        # the cap; test via direct compose call with oversized spec).
        spec = PrintSpec(trim_size=(20000, 20000), bleed=10, safe_area=20)
        page = Page(id="P0", ordering=0, print_spec=spec)
        from stronghold.types.errors import ExportSizeError

        with pytest.raises(ExportSizeError):
            LayerCompositor().compose(page)


# ─── ExportOptions defaults ────────────────────────────────────────────────


class TestExportOptions:
    def test_defaults(self) -> None:
        opts = ExportOptions()
        assert opts.quality == 90
        assert opts.ignore_preflight is False
        assert opts.embed_metadata_pii is False
        assert opts.page_range is None


class TestSupportedFormats:
    def test_lists_supported_formats(self) -> None:
        formats = PrintExporter().supported_formats()
        assert "png" in formats
        assert "pdf" in formats
        assert "jpg" in formats
        assert "webp" in formats
