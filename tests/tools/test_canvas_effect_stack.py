"""Effect stack pipeline — green tests for features/effect-stack.feature.

Implements scenarios that previously lived as skipped stubs in
test_canvas_subsystems.py::TestEffectStack. Backed by PillowEffectApplier
(real Pillow) and the EffectStackRenderer LRU cache.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from stronghold.tools.canvas_effect_stack import EffectStackRenderer
from stronghold.tools.canvas_effects import PillowEffectApplier
from stronghold.types.canvas_design import (
    BlendMode,
    Effect,
    EffectKind,
    Layer,
    LayerTransform,
    RasterSource,
)
from stronghold.types.errors import (
    EffectKindUnknownError,
    EffectParamsError,
    EffectStackOverflowError,
)

# ─── Fixtures ──────────────────────────────────────────────────────────────


def _png_solid(width: int, height: int, rgba: tuple[int, int, int, int]) -> bytes:
    img = Image.new("RGBA", (width, height), color=rgba)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_gradient(width: int, height: int) -> bytes:
    img = Image.new("RGBA", (width, height))
    pixels = img.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (x * 255 // max(1, width - 1), y * 255 // max(1, height - 1), 128, 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def applier() -> PillowEffectApplier:
    return PillowEffectApplier()


@pytest.fixture
def renderer(applier: PillowEffectApplier) -> EffectStackRenderer:
    return EffectStackRenderer(applier=applier)


@pytest.fixture
def sample_png() -> bytes:
    return _png_gradient(32, 32)


# ─── §01 effect-stack.feature scenarios ────────────────────────────────────


class TestEmptyStack:
    """Scenario: Empty effect stack renders the source unchanged."""

    def test_empty_stack_returns_source_bytes(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        result = renderer.render(sample_png, ())
        assert result == sample_png


class TestDisabledEffects:
    """Scenario: Disabled effects are skipped during render."""

    def test_disabled_brightness_is_passthrough(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="e1", kind=EffectKind.BRIGHTNESS, params={"value": 0.5}, enabled=False)
        result = renderer.render(sample_png, (eff,))
        assert result == sample_png


class TestApplyEffects:
    def test_brightness_changes_bytes(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="e1", kind=EffectKind.BRIGHTNESS, params={"value": 0.4})
        result = renderer.render(sample_png, (eff,))
        assert result != sample_png

    def test_brightness_zero_is_identity_pixels(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="e1", kind=EffectKind.BRIGHTNESS, params={"value": 0.0})
        result = renderer.render(sample_png, (eff,))
        assert _pixels(result) == _pixels(sample_png)

    def test_invert_is_its_own_inverse(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="i1", kind=EffectKind.INVERT, params={})
        once = renderer.render(sample_png, (eff,))
        eff2 = Effect(id="i2", kind=EffectKind.INVERT, params={})
        twice = renderer.render(once, (eff2,))
        assert _pixels(twice) == _pixels(sample_png)

    def test_gaussian_blur_radius_zero_is_identity(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="b1", kind=EffectKind.GAUSSIAN_BLUR, params={"radius_px": 0.0})
        result = renderer.render(sample_png, (eff,))
        assert _pixels(result) == _pixels(sample_png)

    def test_gaussian_blur_softens_gradient(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="b1", kind=EffectKind.GAUSSIAN_BLUR, params={"radius_px": 4.0})
        result = renderer.render(sample_png, (eff,))
        # A blur reduces standard deviation across neighbouring pixels.
        src_var = _pixel_variance(sample_png)
        out_var = _pixel_variance(result)
        assert out_var < src_var


class TestReorderingMatters:
    """Scenario: Reordering effects produces different render output."""

    def test_blur_then_pixelate_differs_from_pixelate_then_blur(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        blur = Effect(id="b", kind=EffectKind.GAUSSIAN_BLUR, params={"radius_px": 4.0})
        pixelate = Effect(id="p", kind=EffectKind.PIXELATE, params={"size_px": 4.0})
        order_a = renderer.render(sample_png, (blur, pixelate))
        renderer.clear_cache()
        order_b = renderer.render(sample_png, (pixelate, blur))
        assert _pixels(order_a) != _pixels(order_b)


class TestSameLogicalState:
    """Scenario: Same logical state produces byte-identical render."""

    def test_no_op_round_trip_byte_identical(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="e", kind=EffectKind.BRIGHTNESS, params={"value": 0.2})
        a = renderer.render(sample_png, (eff,))
        b = renderer.render(sample_png, (eff,))
        assert a == b


class TestCache:
    """Scenarios: Cache hit on identical input + invalidation on change."""

    def test_cache_hit_on_identical_input(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        eff = Effect(id="e", kind=EffectKind.BRIGHTNESS, params={"value": 0.2})
        renderer.render(sample_png, (eff,))
        assert renderer.hits == 0
        assert renderer.misses == 1
        renderer.render(sample_png, (eff,))
        assert renderer.hits == 1
        assert renderer.misses == 1

    def test_cache_invalidated_on_param_change(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        first = Effect(id="e", kind=EffectKind.BRIGHTNESS, params={"value": 0.2})
        second = Effect(id="e", kind=EffectKind.BRIGHTNESS, params={"value": 0.5})
        renderer.render(sample_png, (first,))
        renderer.render(sample_png, (second,))
        assert renderer.misses == 2

    def test_disabled_effect_in_middle_keeps_cache_warm(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        a = Effect(id="a", kind=EffectKind.BRIGHTNESS, params={"value": 0.2})
        b_off = Effect(id="b", kind=EffectKind.SHARPEN, params={"amount": 1.0}, enabled=False)
        # First render with disabled middle effect populates cache for the
        # active subset.
        renderer.render(sample_png, (a, b_off))
        # Second render with the disabled effect *removed* should hit cache —
        # because the active subset hashes identically.
        renderer.render(sample_png, (a,))
        assert renderer.hits == 1


class TestStackOverflow:
    """Scenario: Stack overflow at 33rd effect."""

    def test_33rd_effect_raises(self, renderer: EffectStackRenderer, sample_png: bytes) -> None:
        effects = tuple(Effect(id=f"e{i}", kind=EffectKind.INVERT, params={}) for i in range(33))
        with pytest.raises(EffectStackOverflowError):
            renderer.render(sample_png, effects)


class TestApplierSupport:
    """Applier reports kind support correctly + raises on unknown."""

    def test_supports_returns_true_for_handled_kinds(self, applier: PillowEffectApplier) -> None:
        assert applier.supports(EffectKind.BRIGHTNESS)
        assert applier.supports(EffectKind.GAUSSIAN_BLUR)
        assert applier.supports(EffectKind.INVERT)

    def test_supports_returns_false_for_unhandled_kinds(self, applier: PillowEffectApplier) -> None:
        # MOTION_BLUR is in the param-rules table (so it can be constructed)
        # but not yet implemented in the applier dispatch.
        assert not applier.supports(EffectKind.MOTION_BLUR)

    def test_apply_unhandled_kind_raises(
        self, applier: PillowEffectApplier, sample_png: bytes
    ) -> None:
        eff = Effect(id="m1", kind=EffectKind.MOTION_BLUR, params={"radius_px": 8.0, "angle": 0.0})
        with pytest.raises(EffectKindUnknownError):
            applier.apply(sample_png, eff)


class TestParamValidation:
    """Effect construction itself rejects bad params (cross-check)."""

    def test_brightness_out_of_range_rejected(self) -> None:
        with pytest.raises(EffectParamsError):
            Effect(id="e", kind=EffectKind.BRIGHTNESS, params={"value": 9.0})


class TestVignette:
    """Scenario: Vignette darkens corners."""

    def test_vignette_corners_darker_than_centre(
        self, renderer: EffectStackRenderer, applier: PillowEffectApplier
    ) -> None:
        # Use a uniform-grey image so any spatial darkening is purely the vignette
        sample = _png_solid(64, 64, (180, 180, 180, 255))
        eff = Effect(id="v", kind=EffectKind.VIGNETTE, params={"strength": 0.7, "roundness": 0.5})
        result = renderer.render(sample, (eff,))
        out = _load(result)
        centre = _luminance(out.getpixel((32, 32)))
        corner = _luminance(out.getpixel((1, 1)))
        assert corner < centre


class TestExposureGamma:
    def test_exposure_increases_brightness(self, renderer: EffectStackRenderer) -> None:
        sample = _png_solid(8, 8, (100, 100, 100, 255))
        eff = Effect(id="e", kind=EffectKind.EXPOSURE, params={"stops": 1.0})
        result = renderer.render(sample, (eff,))
        out = _load(result)
        assert _luminance(out.getpixel((4, 4))) > 100

    def test_gamma_below_one_darkens(self, renderer: EffectStackRenderer) -> None:
        sample = _png_solid(8, 8, (128, 128, 128, 255))
        eff = Effect(id="g", kind=EffectKind.GAMMA, params={"value": 0.5})
        result = renderer.render(sample, (eff,))
        out = _load(result)
        assert _luminance(out.getpixel((4, 4))) < 128


class TestProtocolConformance:
    def test_pillow_effect_applier_satisfies_protocol(self) -> None:
        from stronghold.protocols.canvas_design import EffectApplier

        assert isinstance(PillowEffectApplier(), EffectApplier)


class TestIntegrationWithLayer:
    """Layer + renderer interop (sanity)."""

    def test_layer_with_two_effects_renders_through_stack(
        self, renderer: EffectStackRenderer, sample_png: bytes
    ) -> None:
        layer = Layer(
            id="L",
            name="x",
            source=RasterSource(blob_id="b", width=32, height=32, inline_bytes=sample_png),
            effects=(
                Effect(id="e1", kind=EffectKind.BRIGHTNESS, params={"value": 0.2}),
                Effect(id="e2", kind=EffectKind.SATURATION, params={"value": -0.3}),
            ),
            transform=LayerTransform(),
            blend_mode=BlendMode.NORMAL,
            opacity=1.0,
        )
        # Pull bytes out of inline_bytes (used in tests) and render via the
        # standalone renderer; full Layer→pipeline composition arrives in a
        # later slice with LayerRenderer.
        assert isinstance(layer.source, RasterSource)
        assert layer.source.inline_bytes is not None
        rendered = renderer.render(layer.source.inline_bytes, layer.effects)
        assert rendered != layer.source.inline_bytes


# ─── helpers ───────────────────────────────────────────────────────────────


def _load(png_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(png_bytes))
    img.load()
    return img.convert("RGBA")


def _pixels(png_bytes: bytes) -> bytes:
    """Raw RGBA byte buffer; bytewise comparison is faster + Pillow-13-clean."""
    return _load(png_bytes).tobytes()


def _luminance(px: object) -> float:
    # px is RGBA tuple after our _load conversion.
    assert isinstance(px, tuple)
    r, g, b, _a = (int(c) for c in px[:4])
    return 0.299 * r + 0.587 * g + 0.114 * b


def _pixel_variance(png_bytes: bytes) -> float:
    img = _load(png_bytes).convert("L")
    raw: list[int] = list(img.tobytes())
    if not raw:
        return 0.0
    mean = float(sum(raw)) / len(raw)
    return float(sum((p - mean) ** 2 for p in raw) / len(raw))
