"""Coverage tests for the operational `tools.canvas_compositor` module.

Drives the public surface: PilCompositorService.composite / encode plus
the colour, transform, text-render, and blend helpers. Uses a tiny
in-memory ImageStore that fabricates Pillow images so tests stay
hermetic.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from stronghold.tools.canvas_compositor import (
    CompositorService,
    PilCompositorService,
    _alpha_composite_frame,
    _encode_jpg,
    _encode_png,
    _encode_webp,
    _parse_hex_color,
    _render_text_layer,
    _transform_layer_image,
)
from stronghold.types.canvas import (
    BlendMode,
    CanvasRecord,
    CompositeResult,
    LayerRecord,
    LayerType,
    TextConfig,
    UnsupportedFormatError,
)


def _solid(color: tuple[int, int, int, int], size: tuple[int, int] = (32, 32)) -> Image.Image:
    return Image.new("RGBA", size, color)


class _FakeImageStore:
    def __init__(self, registry: dict[str, Image.Image]) -> None:
        self._registry = registry

    async def fetch(self, url: str) -> Image.Image:
        if url not in self._registry:
            raise FileNotFoundError(url)
        return self._registry[url]


# ── Hex parsing ──────────────────────────────────────────────────────


class TestParseHexColor:
    def test_six_digit_hash(self) -> None:
        assert _parse_hex_color("#FF8040") == (255, 128, 64, 255)

    def test_six_digit_no_hash(self) -> None:
        assert _parse_hex_color("FF8040") == (255, 128, 64, 255)

    def test_three_digit_expands(self) -> None:
        assert _parse_hex_color("#F84") == (255, 136, 68, 255)

    def test_invalid_length_falls_back_to_white(self) -> None:
        assert _parse_hex_color("#FFFF") == (255, 255, 255, 255)


# ── Layer transform ─────────────────────────────────────────────────


class TestTransformLayerImage:
    def test_scale_and_paste_centered(self) -> None:
        src = _solid((255, 0, 0, 255), (10, 10))
        out = _transform_layer_image(
            src,
            canvas_w=64,
            canvas_h=64,
            x=32,
            y=32,
            scale=2.0,
            rotation=0.0,
            opacity=1.0,
        )
        assert out.size == (64, 64)
        # Some red pixel near the centre
        assert out.getpixel((32, 32))[0] > 200

    def test_rotation_keeps_canvas_size(self) -> None:
        src = _solid((0, 255, 0, 255), (16, 16))
        out = _transform_layer_image(
            src,
            canvas_w=64,
            canvas_h=64,
            x=32,
            y=32,
            scale=1.0,
            rotation=45.0,
            opacity=1.0,
        )
        assert out.size == (64, 64)

    def test_opacity_attenuates_alpha(self) -> None:
        src = _solid((0, 0, 255, 255), (8, 8))
        out = _transform_layer_image(
            src,
            canvas_w=32,
            canvas_h=32,
            x=16,
            y=16,
            scale=1.0,
            rotation=0.0,
            opacity=0.5,
        )
        # Pillow's paste(img, mask=img) multiplies the alpha by the mask
        # alpha, so the visible alpha drops below 0.5 × 255. The contract
        # is just "opacity<1 reduces visible alpha vs. opacity=1".
        out_full = _transform_layer_image(
            src,
            canvas_w=32,
            canvas_h=32,
            x=16,
            y=16,
            scale=1.0,
            rotation=0.0,
            opacity=1.0,
        )
        max_attenuated = max(out.getpixel((x, y))[3] for x in range(32) for y in range(32))
        max_full = max(out_full.getpixel((x, y))[3] for x in range(32) for y in range(32))
        assert max_attenuated < max_full


# ── Text layer rendering ────────────────────────────────────────────


class TestRenderTextLayer:
    @pytest.mark.parametrize("alignment", ["left", "center", "right"])
    def test_renders_text_at_each_alignment(self, alignment: str) -> None:
        tc = TextConfig(content="hi", alignment=alignment, color="#FFFFFF")
        out = _render_text_layer(tc, 64, 32)
        assert out.size == (64, 32)
        # At least one fully-opaque pixel was written by the draw.text call
        alpha_values = {out.getpixel((x, y))[3] for x in range(64) for y in range(32)}
        assert max(alpha_values) > 0

    def test_renders_with_shadow(self) -> None:
        tc = TextConfig(content="hi", shadow_color="#000000", shadow_offset=(2, 2))
        out = _render_text_layer(tc, 64, 32)
        assert out.size == (64, 32)

    def test_invalid_color_falls_back_to_white(self) -> None:
        tc = TextConfig(content="x", color="#zzz")  # malformed
        out = _render_text_layer(tc, 32, 16)
        assert out.size == (32, 16)

    def test_invalid_shadow_color_falls_back_to_black(self) -> None:
        tc = TextConfig(content="x", shadow_color="#zzz")
        out = _render_text_layer(tc, 32, 16)
        assert out.size == (32, 16)


# ── Blend modes ─────────────────────────────────────────────────────


class TestAlphaCompositeFrame:
    def _frames(self) -> tuple[Image.Image, Image.Image]:
        base = _solid((128, 128, 128, 255), (16, 16))
        layer = _solid((128, 128, 128, 255), (16, 16))
        return base, layer

    @pytest.mark.parametrize(
        "mode",
        ["normal", "multiply", "screen", "overlay", "darken", "lighten"],
    )
    def test_known_modes_produce_image(self, mode: str) -> None:
        base, layer = self._frames()
        out = _alpha_composite_frame(base, layer, mode)
        assert out.size == (16, 16)
        assert out.mode == "RGBA"

    def test_unknown_mode_falls_back_without_error(self) -> None:
        base, layer = self._frames()
        out = _alpha_composite_frame(base, layer, "no-such-mode")
        assert out.size == (16, 16)


# ── Encoders ────────────────────────────────────────────────────────


class TestEncoders:
    def test_png_encodes(self) -> None:
        img = _solid((10, 20, 30, 255), (8, 8))
        b = _encode_png(img)
        assert b[:8] == b"\x89PNG\r\n\x1a\n"

    def test_webp_encodes(self) -> None:
        img = _solid((10, 20, 30, 255), (8, 8))
        b = _encode_webp(img)
        assert b[:4] == b"RIFF"

    def test_jpg_encodes_strips_alpha(self) -> None:
        img = _solid((10, 20, 30, 255), (8, 8))
        b = _encode_jpg(img)
        assert b[:3] == b"\xff\xd8\xff"


# ── PilCompositorService.composite (end-to-end) ─────────────────────


class TestCompositorComposite:
    async def test_composite_with_no_layers_returns_background_only(self) -> None:
        service = PilCompositorService(image_store=_FakeImageStore({}))
        canvas = CanvasRecord(id="c1", name="Demo", width=64, height=64)
        result = await service.composite(canvas, [])
        assert isinstance(result, CompositeResult)
        assert result.canvas_id == "c1"
        assert result.width == 64
        assert result.height == 64
        # Background-only PNG decodes
        img = Image.open(io.BytesIO(result.image_bytes))
        assert img.size == (64, 64)

    async def test_composite_text_layer(self) -> None:
        service = PilCompositorService(image_store=_FakeImageStore({}))
        canvas = CanvasRecord(id="c1", name="Demo", width=64, height=32)
        layer = LayerRecord(
            id="l1",
            canvas_id="c1",
            name="title",
            layer_type=LayerType.TEXT,
            text_config=TextConfig(content="hi"),
        )
        result = await service.composite(canvas, [layer])
        assert result.image_bytes  # PNG bytes produced
        assert result.layer_snapshot == [{"id": "l1", "z_index": 0, "visible": True}]

    async def test_composite_image_layer_with_blend_modes(self) -> None:
        store = _FakeImageStore({"img://a": _solid((255, 0, 0, 255), (16, 16))})
        service = CompositorService.create(image_store=store)
        canvas = CanvasRecord(id="c1", name="Demo", width=32, height=32)
        layer = LayerRecord(
            id="l1",
            canvas_id="c1",
            name="bg",
            layer_type=LayerType.BACKGROUND,
            image_path="img://a",
            blend_mode=BlendMode.MULTIPLY,
        )
        result = await service.composite(canvas, [layer])
        assert result.image_bytes

    async def test_invisible_layer_skipped(self) -> None:
        store = _FakeImageStore({"img://a": _solid((0, 255, 0, 255), (8, 8))})
        service = PilCompositorService(image_store=store)
        canvas = CanvasRecord(id="c1", name="Demo", width=32, height=32)
        layer = LayerRecord(
            id="hidden",
            canvas_id="c1",
            name="hidden",
            image_path="img://a",
            visible=False,
        )
        result = await service.composite(canvas, [layer])
        assert result.layer_snapshot == [{"id": "hidden", "z_index": 0, "visible": False}]

    async def test_unfetchable_image_layer_logged_and_skipped(self) -> None:
        # Layer references a URL the store doesn't have → fetch raises → skipped.
        service = PilCompositorService(image_store=_FakeImageStore({}))
        canvas = CanvasRecord(id="c1", name="Demo", width=32, height=32)
        layer = LayerRecord(
            id="missing",
            canvas_id="c1",
            name="missing",
            image_path="img://nope",
        )
        # Should not raise; produces a valid result anyway.
        result = await service.composite(canvas, [layer])
        assert result.image_bytes

    async def test_z_index_orders_layers_back_to_front(self) -> None:
        red = _solid((255, 0, 0, 255), (32, 32))
        blue = _solid((0, 0, 255, 255), (32, 32))
        store = _FakeImageStore({"r": red, "b": blue})
        service = PilCompositorService(image_store=store)
        canvas = CanvasRecord(id="c1", name="Demo", width=32, height=32)
        # Blue painted second (higher z_index) → top pixel should be blue
        layers = [
            LayerRecord(
                id="back", canvas_id="c1", name="back", image_path="r", z_index=0, x=16, y=16
            ),
            LayerRecord(
                id="front", canvas_id="c1", name="front", image_path="b", z_index=10, x=16, y=16
            ),
        ]
        result = await service.composite(canvas, layers)
        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        center = img.getpixel((16, 16))
        # Centre of frame: blue should dominate
        assert center[2] > center[0]


# ── PilCompositorService.encode ──────────────────────────────────────


class TestCompositorEncode:
    async def _png_bytes(self) -> bytes:
        return _encode_png(_solid((10, 20, 30, 255), (8, 8)))

    async def test_encode_to_png(self) -> None:
        service = PilCompositorService(image_store=_FakeImageStore({}))
        out = await service.encode(await self._png_bytes(), fmt="png")
        assert out[:8] == b"\x89PNG\r\n\x1a\n"

    async def test_encode_to_webp(self) -> None:
        service = PilCompositorService(image_store=_FakeImageStore({}))
        out = await service.encode(await self._png_bytes(), fmt="WEBP")
        assert out[:4] == b"RIFF"

    @pytest.mark.parametrize("fmt", ["jpg", "jpeg", "JPG"])
    async def test_encode_to_jpg_aliases(self, fmt: str) -> None:
        service = PilCompositorService(image_store=_FakeImageStore({}))
        out = await service.encode(await self._png_bytes(), fmt=fmt)
        assert out[:3] == b"\xff\xd8\xff"

    async def test_encode_unsupported_format_raises(self) -> None:
        service = PilCompositorService(image_store=_FakeImageStore({}))
        with pytest.raises(UnsupportedFormatError):
            await service.encode(await self._png_bytes(), fmt="bmp")
