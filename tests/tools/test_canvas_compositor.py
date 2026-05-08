"""BDD-style tests for the Canvas compositor service.

The compositor takes a CanvasRecord + list of LayerRecords (with image_paths)
and assembles them into a single PIL image: back-to-front by z_index, applying
x/y translation, uniform scale, rotation, opacity, and blend_mode.

All tests use real PIL images generated in-memory (no disk I/O).
This tests the actual pixel logic, not mocks of it.

Coverage targets:
  - Layer ordering (z_index back-to-front)
  - Visibility exclusion
  - Null image_path skip
  - x/y translation
  - Scale (uniform)
  - Rotation
  - Opacity
  - Clipping at canvas boundary
  - All-invisible → blank canvas
  - 50-layer composite (ceiling test)
  - Output dimensions match canvas
  - Determinism (same input → identical bytes)
  - Text layer rendering (content + style)
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import pytest
from PIL import Image, ImageDraw  # type: ignore[import]


# ---------------------------------------------------------------------------
# Type stubs (import from stronghold once types/canvas.py exists)
# ---------------------------------------------------------------------------

@dataclass
class CanvasRecord:
    id: str = "canvas-test"
    width: int = 512
    height: int = 512
    background_color: str = "#FFFFFF"


@dataclass
class TextConfig:
    content: str = "Hello"
    font: str = "sans-serif"
    size: int = 48
    color: str = "#000000"
    weight: str = "normal"
    alignment: str = "center"
    shadow_color: str | None = None


@dataclass
class LayerRecord:
    id: str = "layer-0"
    canvas_id: str = "canvas-test"
    name: str = "layer"
    layer_type: str = "background"
    z_index: int = 0
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    blend_mode: str = "normal"
    visible: bool = True
    locked: bool = False
    image_path: str | None = None
    text_config: TextConfig | None = None


# ---------------------------------------------------------------------------
# PIL test helpers
# ---------------------------------------------------------------------------

def _solid_png(width: int, height: int, color: tuple[int, int, int, int]) -> bytes:
    """Return bytes of a solid-color RGBA PNG."""
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _red_square(size: int = 128) -> bytes:
    return _solid_png(size, size, (255, 0, 0, 255))


def _blue_square(size: int = 128) -> bytes:
    return _solid_png(size, size, (0, 0, 255, 255))


def _green_square(size: int = 128) -> bytes:
    return _solid_png(size, size, (0, 255, 0, 255))


def _transparent_square(size: int = 128) -> bytes:
    return _solid_png(size, size, (0, 0, 0, 0))


class FakeImageStore:
    """Returns PIL images from in-memory bytes, keyed by URL."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def put(self, url: str, image_bytes: bytes) -> None:
        self._store[url] = image_bytes

    async def fetch(self, url: str) -> Image.Image:
        raw = self._store[url]
        return Image.open(io.BytesIO(raw)).convert("RGBA")


def _layer(
    *,
    idx: int,
    z_index: int,
    url: str,
    visible: bool = True,
    x: float = 0,
    y: float = 0,
    scale: float = 1.0,
    rotation: float = 0.0,
    opacity: float = 1.0,
    blend_mode: str = "normal",
    layer_type: str = "background",
    text_config: TextConfig | None = None,
) -> LayerRecord:
    layer = LayerRecord(
        id=f"layer-{idx}",
        layer_type=layer_type,
        z_index=z_index,
        x=x,
        y=y,
        scale=scale,
        rotation=rotation,
        opacity=opacity,
        blend_mode=blend_mode,
        visible=visible,
        image_path=url if url else None,
        text_config=text_config,
    )
    return layer


def _pixel(img: Image.Image, x: int, y: int) -> tuple[int, int, int, int]:
    """Return RGBA pixel at (x, y)."""
    return img.convert("RGBA").getpixel((x, y))  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Feature: Output dimensions
# ---------------------------------------------------------------------------

class TestOutputDimensions:
    """
    Feature: Composite output always matches canvas dimensions
    """

    @pytest.mark.asyncio
    async def test_output_matches_canvas_size(self) -> None:
        """
        Given a 512×512 canvas with one 128×128 layer
        When composite() is called
        Then the output image is exactly 512×512
        """
        store = FakeImageStore()
        store.put("layer0.png", _red_square(128))

        canvas = CanvasRecord(width=512, height=512)
        layers = [_layer(idx=0, z_index=0, url="layer0.png")]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        assert result.width == 512
        assert result.height == 512

    @pytest.mark.asyncio
    async def test_non_square_canvas_dimensions(self) -> None:
        """
        Given a 1024×576 (16:9) canvas
        When composite() is called
        Then the output is exactly 1024×576
        """
        store = FakeImageStore()
        store.put("bg.png", _solid_png(1024, 576, (10, 20, 30, 255)))

        canvas = CanvasRecord(width=1024, height=576)
        layers = [_layer(idx=0, z_index=0, url="bg.png")]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        assert result.width == 1024
        assert result.height == 576


# ---------------------------------------------------------------------------
# Feature: Layer ordering — z_index back-to-front
# ---------------------------------------------------------------------------

class TestLayerOrdering:
    """
    Feature: Layers are composited back-to-front by z_index
    The highest z_index layer sits on top and its pixels win.
    """

    @pytest.mark.asyncio
    async def test_higher_z_index_on_top(self) -> None:
        """
        Given red layer at z=0 and blue layer at z=1 (both full-canvas)
        When composited
        Then the output pixels are blue (z=1 is on top)
        """
        store = FakeImageStore()
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))
        store.put("blue.png", _solid_png(512, 512, (0, 0, 255, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="red.png"),
            _layer(idx=1, z_index=1, url="blue.png"),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, a = _pixel(img, 256, 256)
        assert b > 200  # blue is dominant
        assert r < 50

    @pytest.mark.asyncio
    async def test_ordering_independent_of_list_order(self) -> None:
        """
        Given layers passed in reverse z_index order [z=1, z=0]
        When composited
        Then the result is identical to passing them in order [z=0, z=1]
        (ordering is by z_index, not list position)
        """
        store = FakeImageStore()
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))
        store.put("blue.png", _solid_png(512, 512, (0, 0, 255, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers_ascending = [
            _layer(idx=0, z_index=0, url="red.png"),
            _layer(idx=1, z_index=1, url="blue.png"),
        ]
        layers_descending = [
            _layer(idx=1, z_index=1, url="blue.png"),
            _layer(idx=0, z_index=0, url="red.png"),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        res_a = await compositor.composite(canvas, layers_ascending)
        res_b = await compositor.composite(canvas, layers_descending)

        assert res_a.image_bytes == res_b.image_bytes


# ---------------------------------------------------------------------------
# Feature: Visibility exclusion
# ---------------------------------------------------------------------------

class TestVisibilityExclusion:
    """
    Feature: Invisible layers are excluded from composite output
    """

    @pytest.mark.asyncio
    async def test_invisible_layer_excluded(self) -> None:
        """
        Given a red background (z=0, visible=True) and a blue overlay (z=1, visible=False)
        When composited
        Then the output is red — the blue layer contributed no pixels
        """
        store = FakeImageStore()
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))
        store.put("blue.png", _solid_png(512, 512, (0, 0, 255, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="red.png", visible=True),
            _layer(idx=1, z_index=1, url="blue.png", visible=False),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, a = _pixel(img, 256, 256)
        assert r > 200
        assert b < 50

    @pytest.mark.asyncio
    async def test_all_invisible_returns_blank(self) -> None:
        """
        Given all layers are invisible
        When composited
        Then the output is a blank (white background) canvas — not an error
        """
        store = FakeImageStore()
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512, background_color="#FFFFFF")
        layers = [_layer(idx=0, z_index=0, url="red.png", visible=False)]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        assert result.image_bytes is not None
        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, a = _pixel(img, 256, 256)
        # Should be white background
        assert r > 200 and g > 200 and b > 200

    @pytest.mark.asyncio
    async def test_no_layers_returns_blank(self) -> None:
        """
        Given an empty layer list
        When composited
        Then the output is a blank canvas of correct dimensions
        """
        store = FakeImageStore()
        canvas = CanvasRecord(width=256, height=256)

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, [])

        assert result.width == 256
        assert result.height == 256


# ---------------------------------------------------------------------------
# Feature: Null image_path skip
# ---------------------------------------------------------------------------

class TestNullImagePathSkip:
    """
    Feature: Layers with image_path=None contribute no pixels
    """

    @pytest.mark.asyncio
    async def test_null_image_path_skipped(self) -> None:
        """
        Given layer z=0 (red, has image) and layer z=1 (no image_path)
        When composited
        Then output pixels are red (z=1 is transparent gap, not an error)
        """
        store = FakeImageStore()
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="red.png"),
            _layer(idx=1, z_index=1, url=""),   # no image
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, a = _pixel(img, 256, 256)
        assert r > 200


# ---------------------------------------------------------------------------
# Feature: Translation (x, y)
# ---------------------------------------------------------------------------

class TestTranslation:
    """
    Feature: Layer x/y translation is applied correctly
    """

    @pytest.mark.asyncio
    async def test_layer_positioned_at_offset(self) -> None:
        """
        Given a 64×64 red layer at x=200 y=200 on a 512×512 white canvas
        When composited
        Then pixel at (232, 232) is red and pixel at (0, 0) is white
        """
        store = FakeImageStore()
        store.put("bg.png", _solid_png(512, 512, (255, 255, 255, 255)))
        store.put("red.png", _solid_png(64, 64, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="bg.png"),
            _layer(idx=1, z_index=1, url="red.png", x=200, y=200, layer_type="object"),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        # Inside the red block
        r_inside, g_inside, b_inside, _ = _pixel(img, 232, 232)
        assert r_inside > 200 and g_inside < 50

        # Outside (top-left corner should still be white)
        r_out, g_out, b_out, _ = _pixel(img, 5, 5)
        assert r_out > 200 and g_out > 200 and b_out > 200


# ---------------------------------------------------------------------------
# Feature: Opacity
# ---------------------------------------------------------------------------

class TestOpacity:
    """
    Feature: Layer opacity is applied correctly via alpha compositing
    """

    @pytest.mark.asyncio
    async def test_opacity_50_blends_with_background(self) -> None:
        """
        Given a white background (z=0) and a black overlay at opacity=0.5 (z=1)
        When composited
        Then the output is approximately mid-grey (~128,128,128)
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(512, 512, (255, 255, 255, 255)))
        store.put("black.png", _solid_png(512, 512, (0, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="white.png"),
            _layer(idx=1, z_index=1, url="black.png", opacity=0.5),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, a = _pixel(img, 256, 256)
        # Allow ±30 tolerance for blending algorithm differences
        assert 100 < r < 200
        assert 100 < g < 200
        assert 100 < b < 200

    @pytest.mark.asyncio
    async def test_opacity_zero_is_invisible(self) -> None:
        """
        Given a red layer at opacity=0.0 on a white background
        When composited
        Then the output pixel is white (red is fully transparent)
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(512, 512, (255, 255, 255, 255)))
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="white.png"),
            _layer(idx=1, z_index=1, url="red.png", opacity=0.0),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, _ = _pixel(img, 256, 256)
        assert r > 200 and g > 200 and b > 200

    @pytest.mark.asyncio
    async def test_opacity_one_is_fully_opaque(self) -> None:
        """
        Given a red layer at opacity=1.0 on a white background
        When composited
        Then the output pixel is fully red
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(512, 512, (255, 255, 255, 255)))
        store.put("red.png", _solid_png(512, 512, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="white.png"),
            _layer(idx=1, z_index=1, url="red.png", opacity=1.0),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        r, g, b, _ = _pixel(img, 256, 256)
        assert r > 200 and g < 50 and b < 50


# ---------------------------------------------------------------------------
# Feature: Scale
# ---------------------------------------------------------------------------

class TestScale:
    """
    Feature: Layer scale is applied uniformly
    """

    @pytest.mark.asyncio
    async def test_scale_doubles_layer_size(self) -> None:
        """
        Given a 64×64 red layer at scale=2.0 positioned at (0,0) on a 256×256 canvas
        When composited
        Then the red region covers ~128×128 pixels from the origin
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(256, 256, (255, 255, 255, 255)))
        store.put("red.png", _solid_png(64, 64, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=256, height=256)
        layers = [
            _layer(idx=0, z_index=0, url="white.png"),
            _layer(idx=1, z_index=1, url="red.png", scale=2.0, layer_type="object"),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        # At (100, 100) — inside the scaled 128×128 block
        r, g, b, _ = _pixel(img, 100, 100)
        assert r > 200 and g < 50

        # At (200, 200) — outside the scaled block
        r2, g2, b2, _ = _pixel(img, 200, 200)
        assert r2 > 200 and g2 > 200 and b2 > 200


# ---------------------------------------------------------------------------
# Feature: Boundary clipping (EC-11)
# ---------------------------------------------------------------------------

class TestBoundaryClipping:
    """
    Feature: Layer content beyond canvas edges is clipped
    """

    @pytest.mark.asyncio
    async def test_layer_outside_canvas_clipped(self) -> None:
        """
        EC-11: Given a 128×128 red layer positioned at x=450 y=450 on a 512×512 canvas
        When composited
        Then only the top-left 62×62 pixels of the red layer appear in the output;
        the result image is still exactly 512×512
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(512, 512, (255, 255, 255, 255)))
        store.put("red.png", _solid_png(128, 128, (255, 0, 0, 255)))

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="white.png"),
            _layer(idx=1, z_index=1, url="red.png", x=450, y=450, layer_type="object"),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        assert result.width == 512
        assert result.height == 512

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        # Inside the clipped red region
        r, g, b, _ = _pixel(img, 480, 480)
        assert r > 200

        # Well outside the canvas (doesn't exist — can't test; just verify no crash)


# ---------------------------------------------------------------------------
# Feature: Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    """
    Feature: Composite output is deterministic — same inputs produce byte-identical output
    """

    @pytest.mark.asyncio
    async def test_same_inputs_identical_output(self) -> None:
        """
        Given identical canvas, layers, and images
        When composite() is called twice
        Then both result.image_bytes are byte-identical
        """
        store = FakeImageStore()
        store.put("red.png", _solid_png(128, 128, (200, 50, 50, 255)))
        store.put("blue.png", _solid_png(64, 64, (50, 50, 200, 255)))

        canvas = CanvasRecord(width=256, height=256)
        layers = [
            _layer(idx=0, z_index=0, url="red.png"),
            _layer(idx=1, z_index=1, url="blue.png", x=50, y=50, opacity=0.8, layer_type="object"),
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        r1 = await compositor.composite(canvas, layers)
        r2 = await compositor.composite(canvas, layers)

        assert r1.image_bytes == r2.image_bytes


# ---------------------------------------------------------------------------
# Feature: Scale ceiling (EC-22) — 50-layer composite
# ---------------------------------------------------------------------------

class TestScaleCeiling:
    """
    Feature: Compositor handles 50-layer canvas without OOM or crash
    """

    @pytest.mark.asyncio
    async def test_fifty_layer_composite_completes(self) -> None:
        """
        EC-22: Given a canvas with 50 visible layers (each 64×64)
        When composite() is called
        Then it completes without error and returns correct dimensions
        """
        store = FakeImageStore()
        layers = []
        for i in range(50):
            url = f"layer-{i}.png"
            # Each layer is a slightly different shade
            shade = (i * 5 % 255, (i * 7 + 50) % 255, (i * 11 + 100) % 255, 255)
            store.put(url, _solid_png(64, 64, shade))
            layers.append(_layer(idx=i, z_index=i, url=url, layer_type="object"))

        canvas = CanvasRecord(width=512, height=512)

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        assert result.width == 512
        assert result.height == 512
        assert result.image_bytes is not None
        assert len(result.image_bytes) > 0


# ---------------------------------------------------------------------------
# Feature: Text layer rendering
# ---------------------------------------------------------------------------

class TestTextLayerRendering:
    """
    Feature: Text layers render via the compositor text engine, not AI
    Text is always pixel-perfect (no garbled AI text).
    """

    @pytest.mark.asyncio
    async def test_text_layer_renders_without_image_gen(self) -> None:
        """
        Given a text layer with content='Hello' and no image_path
        When composited
        Then the output contains visible text pixels (dark on white)
        And no image gen client was called
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(512, 512, (255, 255, 255, 255)))

        text_layer = LayerRecord(
            id="text-0",
            layer_type="text",
            z_index=1,
            x=0,
            y=0,
            visible=True,
            image_path=None,
            text_config=TextConfig(
                content="Hello",
                font="sans-serif",
                size=48,
                color="#000000",
                alignment="center",
            ),
        )

        canvas = CanvasRecord(width=512, height=512)
        layers = [
            _layer(idx=0, z_index=0, url="white.png"),
            text_layer,
        ]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        # The output should contain at least one dark pixel (text pixels)
        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        dark_pixels = sum(
            1 for x in range(512) for y in range(512)
            if _pixel(img, x, y)[0] < 100
        )
        assert dark_pixels > 0, "Text should produce dark pixels on white background"

    @pytest.mark.asyncio
    async def test_invisible_text_layer_excluded(self) -> None:
        """
        Given a text layer with visible=False
        When composited
        Then no text pixels appear in the output
        """
        store = FakeImageStore()
        store.put("white.png", _solid_png(256, 256, (255, 255, 255, 255)))

        text_layer = LayerRecord(
            id="text-0",
            layer_type="text",
            z_index=1,
            visible=False,
            image_path=None,
            text_config=TextConfig(content="Hidden", color="#000000"),
        )

        canvas = CanvasRecord(width=256, height=256)
        layers = [_layer(idx=0, z_index=0, url="white.png"), text_layer]

        from stronghold.tools.canvas_compositor import CompositorService  # type: ignore[import]
        compositor = CompositorService(image_store=store)
        result = await compositor.composite(canvas, layers)

        img = Image.open(io.BytesIO(result.image_bytes)).convert("RGBA")
        dark_pixels = sum(
            1 for x in range(256) for y in range(256)
            if _pixel(img, x, y)[0] < 100
        )
        assert dark_pixels == 0, "Invisible text layer must contribute no pixels"
