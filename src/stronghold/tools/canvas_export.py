"""Export pipeline (spec §13).

Renders a `Document` into bytes in the requested format. Composition
goes through `LayerCompositor` which walks pages, sorts layers by
z_index, applies effects via the `EffectApplier`, and blends layers
onto the page background.

Supported formats in this slice:
  - PNG   single page or multi-page → ZIP
  - JPG   single page only (no alpha)
  - WEBP  single page or multi-page → ZIP
  - PDF   raster-flatten via Pillow's native PDF (multi-page native)

Vector text/shape rendering uses a minimal Pillow ImageDraw path. Shape
rendering currently supports the common kinds (RECTANGLE, ELLIPSE,
LINE) — exotic kinds (PATH, ARROW, etc.) will be added in a later slice.

Pre-flight is invoked before export by default; FAIL aborts unless
`ignore_preflight=True`. The audit trail records every export.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont

from stronghold.types.canvas_design import (
    BlendMode,
    Color,
    Document,
    GroupSource,
    Layer,
    Page,
    RasterSource,
    ReportLevel,
    ShapeKind,
    ShapeSource,
    TextSource,
)
from stronghold.types.errors import (
    EmptyDocumentError,
    ExportBackendError,
    ExportFormatUnsupportedError,
    ExportSizeError,
    PreflightFailedError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stronghold.tools.canvas_effects import PillowEffectApplier
    from stronghold.types.canvas_design import PreflightReport

logger = logging.getLogger("stronghold.tools.canvas_export")


# Hard cap to protect against accidental absurd dims (e.g. corrupted spec).
_MAX_PIXEL_AREA = 200_000_000  # ~14k × 14k


# ---------------------------------------------------------------------------
# ExportOptions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExportOptions:
    """Per-call overrides for the export pipeline (spec §13)."""

    page_range: tuple[int, int] | None = None
    quality: int = 90
    ignore_preflight: bool = False
    embed_metadata_pii: bool = False
    inline_raster: bool = False
    enforce_proof: bool = False


# ---------------------------------------------------------------------------
# Layer compositor
# ---------------------------------------------------------------------------


_BLEND_TO_PIL: dict[BlendMode, str | None] = {
    BlendMode.NORMAL: None,
    BlendMode.MULTIPLY: "multiply",
    BlendMode.SCREEN: "screen",
    BlendMode.DARKEN: "darken",
    BlendMode.LIGHTEN: "lighten",
}


class LayerCompositor:
    """Compose a `Page` into a single PIL Image at bleed dimensions.

    Layers render head-to-tail by z_index. Effects (if applied) flow
    through the `applier`. Each layer's transform x/y/scale is honoured;
    rotation is supported via PIL's transform-with-rotate.
    """

    def __init__(self, *, applier: PillowEffectApplier | None = None) -> None:
        self._applier = applier

    def compose(self, page: Page) -> Image.Image:
        bw, bh = page.print_spec.bleed_canvas
        if bw * bh > _MAX_PIXEL_AREA:
            raise ExportSizeError(
                f"page {page.id!r} bleed canvas {bw}x{bh} exceeds {_MAX_PIXEL_AREA}px"
            )
        canvas = Image.new("RGBA", (bw, bh), color=_to_rgba(page.background))
        for layer in sorted(page.layers, key=lambda layer_: layer_.z_index):
            if not layer.visible:
                continue
            rendered = self._render_layer(layer, page)
            if rendered is None:
                continue
            self._composite_into(canvas, rendered, layer)
        return canvas

    def _render_layer(self, layer: Layer, page: Page) -> Image.Image | None:
        src = layer.source
        if isinstance(src, RasterSource):
            if src.inline_bytes is None:
                logger.debug(
                    "layer %s has no inline bytes; production path requires blob resolver", layer.id
                )
                return None
            img = Image.open(io.BytesIO(src.inline_bytes))
            img.load()
            return self._apply_effects(img.convert("RGBA"), layer)
        if isinstance(src, TextSource):
            return self._render_text(src, page, layer)
        if isinstance(src, ShapeSource):
            return self._render_shape(src, layer)
        if isinstance(src, GroupSource):
            # Group composition not in this slice; skip with debug log.
            logger.debug("skipping group layer %s — group composition deferred", layer.id)
            return None
        return None

    def _apply_effects(self, image: Image.Image, layer: Layer) -> Image.Image:
        if not layer.effects or self._applier is None:
            return image
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        result = buf.getvalue()
        for effect in layer.effects:
            if not effect.enabled:
                continue
            result = self._applier.apply(result, effect)
        return Image.open(io.BytesIO(result)).convert("RGBA")

    def _render_text(self, src: TextSource, page: Page, layer: Layer) -> Image.Image:
        # Pillow's default font for width measurement; production resolves
        # fonts via the font registry (future slice).
        try:
            font = ImageFont.load_default()
        except OSError as exc:  # pragma: no cover  defensive
            raise ExportBackendError(f"failed to load default font: {exc}") from exc
        bbox = font.getbbox(src.content)
        text_w = max(1, bbox[2] - bbox[0])
        text_h = max(1, bbox[3] - bbox[1])
        # Layer transform.scale grows the rendered box.
        canvas_w = max(1, int(text_w * layer.transform.scale))
        canvas_h = max(1, int(text_h * layer.transform.scale))
        canvas = Image.new("RGBA", (canvas_w, canvas_h), color=(0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), src.content, font=font, fill=_to_rgba(src.style.color))
        # Avoid silently mangling per-page measurements: warn if page DPI
        # is high but font is the default low-res fallback.
        if page.print_spec.dpi >= 300:
            logger.debug(
                "text layer %s rendered with default font at %s DPI — quality limited",
                layer.id,
                page.print_spec.dpi,
            )
        return canvas

    def _render_shape(self, src: ShapeSource, layer: Layer) -> Image.Image | None:
        geometry = src.geometry
        width = int(geometry.get("width", 0))
        height = int(geometry.get("height", 0))
        if src.shape_kind in (ShapeKind.LINE,):
            x1 = int(geometry.get("x1", 0))
            y1 = int(geometry.get("y1", 0))
            x2 = int(geometry.get("x2", 0))
            y2 = int(geometry.get("y2", 0))
            width = max(1, abs(x2 - x1))
            height = max(1, abs(y2 - y1))
        if width <= 0 or height <= 0:
            logger.debug("shape layer %s has zero geometry; skipping", layer.id)
            return None
        canvas = Image.new("RGBA", (width, height), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        fill = _fill_to_rgba(src.fill)
        stroke_color = _to_rgba(src.stroke.color) if src.stroke is not None else None
        stroke_width = int(round(src.stroke.width)) if src.stroke is not None else 0
        if src.shape_kind is ShapeKind.RECTANGLE:
            draw.rounded_rectangle(
                (0, 0, width - 1, height - 1),
                radius=src.corner_radius,
                fill=fill,
                outline=stroke_color,
                width=max(1, stroke_width) if stroke_color else 0,
            )
        elif src.shape_kind is ShapeKind.ELLIPSE:
            draw.ellipse(
                (0, 0, width - 1, height - 1),
                fill=fill,
                outline=stroke_color,
                width=max(1, stroke_width) if stroke_color else 0,
            )
        elif src.shape_kind is ShapeKind.LINE:
            draw.line(
                (0, 0, width - 1, height - 1),
                fill=stroke_color or fill,
                width=max(1, stroke_width),
            )
        else:
            # Other kinds deferred (PATH, ARROW, STAR, etc.)
            logger.debug("shape kind %s not supported in export slice", src.shape_kind)
            return None
        return canvas

    @staticmethod
    def _composite_into(canvas: Image.Image, layer_img: Image.Image, layer: Layer) -> None:
        # Apply scale + rotation
        if layer.transform.scale != 1.0:
            new_w = max(1, int(layer_img.width * layer.transform.scale))
            new_h = max(1, int(layer_img.height * layer.transform.scale))
            layer_img = layer_img.resize((new_w, new_h), Image.Resampling.BILINEAR)
        if layer.transform.rotation != 0.0:
            layer_img = layer_img.rotate(
                -layer.transform.rotation, resample=Image.Resampling.BILINEAR, expand=True
            )
        # Apply opacity
        if layer.opacity < 1.0:
            alpha = layer_img.getchannel("A")
            scaled = alpha.point(lambda a: int(a * layer.opacity))
            layer_img.putalpha(scaled)
        # Blend mode handling (NORMAL → alpha-composite; other simple modes
        # via Pillow ImageChops on the overlapping rect).
        x = layer.transform.x
        y = layer.transform.y
        if layer.blend_mode is BlendMode.NORMAL:
            canvas.alpha_composite(layer_img, dest=(x, y))
            return
        # For non-NORMAL modes, do a rect-aligned blend on the canvas region.
        from PIL import ImageChops  # noqa: PLC0415  — local for cheap import path

        rect = (x, y, x + layer_img.width, y + layer_img.height)
        # Crop to canvas bounds
        if rect[0] >= canvas.width or rect[1] >= canvas.height:
            return
        crop_box = (
            max(0, rect[0]),
            max(0, rect[1]),
            min(canvas.width, rect[2]),
            min(canvas.height, rect[3]),
        )
        if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
            return
        target = canvas.crop(crop_box).convert("RGB")
        # Source crop to align
        src_x = crop_box[0] - rect[0]
        src_y = crop_box[1] - rect[1]
        src_w = crop_box[2] - crop_box[0]
        src_h = crop_box[3] - crop_box[1]
        source = layer_img.crop((src_x, src_y, src_x + src_w, src_y + src_h)).convert("RGB")
        op = _BLEND_TO_PIL.get(layer.blend_mode)
        if op == "multiply":
            blended = ImageChops.multiply(target, source)
        elif op == "screen":
            blended = ImageChops.screen(target, source)
        elif op == "darken":
            blended = ImageChops.darker(target, source)
        elif op == "lighten":
            blended = ImageChops.lighter(target, source)
        else:
            # Fallback to NORMAL alpha-composite
            canvas.alpha_composite(layer_img, dest=(x, y))
            return
        canvas.paste(blended.convert("RGBA"), crop_box)


# ---------------------------------------------------------------------------
# Format encoders
# ---------------------------------------------------------------------------


def _encode_image(
    image: Image.Image,
    *,
    format: str,  # noqa: A002  standard image-encoding parameter name
    quality: int = 90,
) -> bytes:
    buf = io.BytesIO()
    if format in ("JPG", "JPEG"):
        image.convert("RGB").save(buf, format="JPEG", quality=quality)
    elif format == "WEBP":
        image.save(buf, format="WEBP", quality=quality)
    elif format == "PNG":
        image.save(buf, format="PNG")
    else:
        raise ExportFormatUnsupportedError(f"unknown image format: {format}")
    return buf.getvalue()


def _encode_pdf(images: list[Image.Image]) -> bytes:
    if not images:
        raise EmptyDocumentError("PDF export requires at least one page")
    # Pillow native multi-page PDF.
    rgb = [img.convert("RGB") for img in images]
    buf = io.BytesIO()
    rgb[0].save(
        buf,
        format="PDF",
        save_all=True,
        append_images=rgb[1:] if len(rgb) > 1 else [],
        resolution=300.0,
    )
    return buf.getvalue()


def _zip_pages(
    name_prefix: str,
    images: list[Image.Image],
    *,
    format: str,  # noqa: A002  standard image-encoding parameter name
    quality: int = 90,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for i, img in enumerate(images):
            ext = format.lower().replace("jpeg", "jpg")
            zf.writestr(
                f"{name_prefix}_page_{i:03d}.{ext}",
                _encode_image(img, format=format, quality=quality),
            )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Public exporter
# ---------------------------------------------------------------------------


_SUPPORTED_FORMATS = ("png", "jpg", "jpeg", "webp", "pdf")


class PrintExporter:
    """Document → bytes (spec §13).

    The exporter satisfies the `PrintExporter` Protocol; it accepts a
    `Document` directly via `export_document()` and a `(document_id,
    tenant_id)` pair via the Protocol-defined `export()` (which delegates
    to a registered `DocumentStore`).
    """

    def __init__(
        self,
        *,
        compositor: LayerCompositor | None = None,
        preflight_runner: object | None = None,
        document_store: object | None = None,
    ) -> None:
        self._compositor = compositor or LayerCompositor()
        self._preflight = preflight_runner
        self._store = document_store

    def supported_formats(self) -> tuple[str, ...]:
        return _SUPPORTED_FORMATS

    async def export(
        self,
        document_id: str,
        *,
        tenant_id: str,
        format: str,  # noqa: A002
        options: dict[str, Any] | None = None,
    ) -> bytes:
        """Protocol entry point — resolves Document via injected store."""
        if self._store is None:
            raise ExportBackendError(
                "PrintExporter has no DocumentStore injected; use export_document() in tests"
            )
        # In production we'd resolve dict→Document. For this slice the
        # caller can use export_document() directly.
        raise ExportBackendError(
            "Protocol-level export() requires DocumentStore→Document hydration "
            "(deferred). Use export_document(document, ...) for now."
        )

    async def export_document(
        self,
        document: Document,
        *,
        format: str,  # noqa: A002
        options: ExportOptions | None = None,
    ) -> bytes:
        format_norm = format.lower()
        if format_norm not in _SUPPORTED_FORMATS:
            raise ExportFormatUnsupportedError(f"format={format!r} not in {_SUPPORTED_FORMATS}")
        opts = options or ExportOptions()
        if document.page_count == 0:
            raise EmptyDocumentError(f"document {document.id} has no pages")

        await self._gate_via_preflight(document, ignore=opts.ignore_preflight)
        pages = self._select_pages(document, opts.page_range)
        composed: list[Image.Image] = [self._compositor.compose(p) for p in pages]

        if format_norm == "pdf":
            return _encode_pdf(composed)
        if format_norm == "jpg" or format_norm == "jpeg":
            if len(composed) == 1:
                return _encode_image(composed[0], format="JPEG", quality=opts.quality)
            return _zip_pages(document.name or "doc", composed, format="JPEG", quality=opts.quality)
        if format_norm == "png":
            if len(composed) == 1:
                return _encode_image(composed[0], format="PNG", quality=opts.quality)
            return _zip_pages(document.name or "doc", composed, format="PNG", quality=opts.quality)
        if format_norm == "webp":
            if len(composed) == 1:
                return _encode_image(composed[0], format="WEBP", quality=opts.quality)
            return _zip_pages(document.name or "doc", composed, format="WEBP", quality=opts.quality)
        # Should not reach
        raise ExportFormatUnsupportedError(f"unhandled format: {format_norm}")  # pragma: no cover

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _select_pages(document: Document, page_range: tuple[int, int] | None) -> Sequence[Page]:
        ordered = sorted(document.pages, key=lambda page_: page_.ordering)
        if page_range is None:
            return ordered
        lo, hi = page_range
        return [p for p in ordered if lo <= p.ordering <= hi]

    async def _gate_via_preflight(self, document: Document, *, ignore: bool) -> None:
        if self._preflight is None:
            return
        # Inject the document so the in-process PreflightChecker can find it
        if hasattr(self._preflight, "set_document"):
            self._preflight.set_document(document)
        report: PreflightReport = await self._preflight.run(  # type: ignore[attr-defined]
            document.id, tenant_id=document.tenant_id
        )
        if report.summary.failures > 0 and not ignore:
            raise PreflightFailedError(
                f"export blocked: {report.summary.failures} preflight failures"
            )
        if report.level is ReportLevel.FAIL and ignore:
            logger.info(
                "ignoring %d preflight failures on doc %s", report.summary.failures, document.id
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_rgba(color: Color) -> tuple[int, int, int, int]:
    hex_value = color.value.lstrip("#")
    if len(hex_value) == 6:
        r = int(hex_value[0:2], 16)
        g = int(hex_value[2:4], 16)
        b = int(hex_value[4:6], 16)
        return (r, g, b, 255)
    # 8-char RRGGBBAA
    r = int(hex_value[0:2], 16)
    g = int(hex_value[2:4], 16)
    b = int(hex_value[4:6], 16)
    a = int(hex_value[6:8], 16)
    return (r, g, b, a)


def _fill_to_rgba(fill: dict[str, Any]) -> tuple[int, int, int, int] | None:
    kind = fill.get("kind")
    if kind == "none":
        return None
    if kind == "solid":
        color = fill.get("color")
        if isinstance(color, Color):
            return _to_rgba(color)
        if isinstance(color, str):
            return _to_rgba(Color(color))
        return None
    # Gradient/pattern fills not supported in this slice
    return None
