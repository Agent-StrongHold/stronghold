"""Effect application via Pillow (spec §01, §07 P2 minimum).

Implements `EffectApplier` from `protocols.canvas_design`. Per-effect
adapters operate on PNG byte buffers (round-trip via Pillow). Pure
in-process; no external dependencies beyond Pillow.

Supported (P2 minimum):
  Adjustments: BRIGHTNESS, CONTRAST, SATURATION, HUE_SHIFT, EXPOSURE,
               GAMMA, INVERT
  Filters    : GAUSSIAN_BLUR, SHARPEN, UNSHARP_MASK, NOISE_ADD, VIGNETTE,
               PIXELATE
  Layer styles: STROKE (thin scaffold; full drop_shadow/glow deferred)

Effect param schemas are validated at Effect construction time (see
types/canvas_design.py). This applier trusts already-validated Effects.
"""

from __future__ import annotations

import io
import logging
import math
from typing import TYPE_CHECKING

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from stronghold.types.canvas_design import EffectKind
from stronghold.types.errors import EffectKindUnknownError

if TYPE_CHECKING:
    from collections.abc import Callable

    from stronghold.types.canvas_design import Effect

    EffectHandler = Callable[[Image.Image, "dict[str, object]"], Image.Image]

logger = logging.getLogger("stronghold.tools.canvas_effects")


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


class PillowEffectApplier:
    """EffectApplier backed by Pillow.

    `apply(image_bytes, effect) -> bytes` round-trips PNG bytes. Disabled
    effects pass through unchanged (the §01 render pipeline filters them
    out before this point, but the applier is robust either way).
    """

    def supports(self, kind: EffectKind) -> bool:
        return kind in _DISPATCH

    def apply(self, image: bytes, effect: Effect) -> bytes:
        if not effect.enabled:
            return image
        handler = _DISPATCH.get(effect.kind)
        if handler is None:
            raise EffectKindUnknownError(
                f"PillowEffectApplier does not support kind={effect.kind.value}"
            )
        with Image.open(io.BytesIO(image)) as src:
            src.load()
            mode = src.mode if src.mode in ("RGB", "RGBA", "L") else "RGBA"
            working = src.convert(mode)
            result = handler(working, effect.params)
        buf = io.BytesIO()
        result.save(buf, format="PNG")
        return buf.getvalue()


# ---------------------------------------------------------------------------
# Per-kind handlers
# ---------------------------------------------------------------------------


def _brightness(img: Image.Image, params: dict[str, object]) -> Image.Image:
    value = float(params["value"])  # type: ignore[arg-type]
    factor = 1.0 + value
    return ImageEnhance.Brightness(img).enhance(factor)


def _contrast(img: Image.Image, params: dict[str, object]) -> Image.Image:
    value = float(params["value"])  # type: ignore[arg-type]
    factor = 1.0 + value
    return ImageEnhance.Contrast(img).enhance(factor)


def _saturation(img: Image.Image, params: dict[str, object]) -> Image.Image:
    value = float(params["value"])  # type: ignore[arg-type]
    factor = 1.0 + value
    return ImageEnhance.Color(img).enhance(factor)


def _hue_shift(img: Image.Image, params: dict[str, object]) -> Image.Image:
    degrees = float(params["degrees"])  # type: ignore[arg-type]
    if math.isclose(degrees, 0.0):
        return img
    has_alpha = img.mode == "RGBA"
    alpha = img.getchannel("A") if has_alpha else None
    rgb = img.convert("RGB")
    hsv = rgb.convert("HSV")
    h, s, v = hsv.split()
    shift = int(round((degrees / 360.0) * 256.0)) % 256
    h = h.point(lambda px, shift=shift: (px + shift) % 256)
    shifted = Image.merge("HSV", (h, s, v)).convert("RGB")
    if alpha is not None:
        shifted = shifted.convert("RGBA")
        shifted.putalpha(alpha)
    return shifted


def _exposure(img: Image.Image, params: dict[str, object]) -> Image.Image:
    stops = float(params["stops"])  # type: ignore[arg-type]
    factor = 2.0**stops
    return ImageEnhance.Brightness(img).enhance(factor)


def _gamma(img: Image.Image, params: dict[str, object]) -> Image.Image:
    value = float(params["value"])  # type: ignore[arg-type]
    inv = 1.0 / value
    lut = [min(255, max(0, int(round(((i / 255.0) ** inv) * 255.0)))) for i in range(256)]
    return _apply_lut_per_channel(img, lut)


def _invert(img: Image.Image, _params: dict[str, object]) -> Image.Image:
    if img.mode == "RGBA":
        rgb = img.convert("RGB")
        inverted = ImageOps.invert(rgb)
        out = inverted.convert("RGBA")
        out.putalpha(img.getchannel("A"))
        return out
    if img.mode == "L":
        return ImageOps.invert(img)
    return ImageOps.invert(img.convert("RGB"))


def _gaussian_blur(img: Image.Image, params: dict[str, object]) -> Image.Image:
    radius = float(params["radius_px"])  # type: ignore[arg-type]
    if radius <= 0:
        return img
    return img.filter(ImageFilter.GaussianBlur(radius=radius))


def _sharpen(img: Image.Image, params: dict[str, object]) -> Image.Image:
    amount = float(params["amount"])  # type: ignore[arg-type]
    if amount <= 0:
        return img
    return img.filter(ImageFilter.UnsharpMask(radius=2.0, percent=int(amount * 100), threshold=0))


def _unsharp_mask(img: Image.Image, params: dict[str, object]) -> Image.Image:
    radius = float(params["radius_px"])  # type: ignore[arg-type]
    amount = float(params["amount"])  # type: ignore[arg-type]
    if amount <= 0 or radius <= 0:
        return img
    return img.filter(
        ImageFilter.UnsharpMask(radius=radius, percent=int(amount * 100), threshold=0)
    )


def _noise_add(img: Image.Image, params: dict[str, object]) -> Image.Image:
    """Add Gaussian noise without numpy. Cheap per-pixel jitter using PRNG."""
    amount = float(params["amount"])  # type: ignore[arg-type]
    if amount <= 0:
        return img
    # Deterministic seed per call to keep tests reproducible without leaking
    # global random state; key on dims + amount.
    rng = _LCG(seed=img.width * 31 + img.height * 7 + int(amount * 1024))
    sigma = int(round(amount * 64))  # max ±64 of 256
    # Fast path: pre-build a noise image and blend.
    noise = Image.new("L", img.size)
    pixels = noise.load()
    if pixels is None:
        return img  # shouldn't happen; defensive
    for y in range(img.height):
        for x in range(img.width):
            pixels[x, y] = max(0, min(255, 128 + int(rng.next_signed(sigma))))
    if img.mode == "RGBA":
        rgb = img.convert("RGB")
        merged = Image.blend(rgb, noise.convert("RGB"), alpha=amount)
        out = merged.convert("RGBA")
        out.putalpha(img.getchannel("A"))
        return out
    return Image.blend(img.convert("RGB"), noise.convert("RGB"), alpha=amount)


def _vignette(img: Image.Image, params: dict[str, object]) -> Image.Image:
    strength = float(params["strength"])  # type: ignore[arg-type]
    roundness = float(params["roundness"])  # type: ignore[arg-type]
    if strength <= 0:
        return img
    w, h = img.size
    cx, cy = w / 2.0, h / 2.0
    max_d = math.hypot(cx, cy)
    mask = Image.new("L", (w, h))
    pixels = mask.load()
    if pixels is None:
        return img
    aspect = max(0.001, roundness * (max(w, h) / max_d))
    for y in range(h):
        for x in range(w):
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy * aspect)
            t = min(1.0, d / max_d)
            darkness = int(round(255 * (1.0 - strength * (t**2))))
            pixels[x, y] = max(0, min(255, darkness))
    has_alpha = img.mode == "RGBA"
    rgb = img.convert("RGB")
    black = Image.new("RGB", (w, h), color=(0, 0, 0))
    out = Image.composite(rgb, black, mask)
    if has_alpha:
        out = out.convert("RGBA")
        out.putalpha(img.getchannel("A"))
    return out


def _pixelate(img: Image.Image, params: dict[str, object]) -> Image.Image:
    size = int(float(params["size_px"]))  # type: ignore[arg-type]
    if size <= 1:
        return img
    w, h = img.size
    small = img.resize((max(1, w // size), max(1, h // size)), Image.Resampling.NEAREST)
    return small.resize(img.size, Image.Resampling.NEAREST)


def _stroke(img: Image.Image, params: dict[str, object]) -> Image.Image:
    """Draw a stroke around the layer's alpha silhouette.

    Cheap implementation: dilate the alpha by `width` pixels and composite
    the stroke colour over the result. Only meaningful for RGBA inputs.
    """
    width = float(params["width"])  # type: ignore[arg-type]
    if width <= 0 or img.mode != "RGBA":
        return img
    radius = int(math.ceil(width))
    alpha = img.getchannel("A")
    expanded = alpha.filter(ImageFilter.MaxFilter(size=radius * 2 + 1))
    stroke_layer = Image.new("RGBA", img.size, color=(0, 0, 0, 255))
    out = Image.composite(stroke_layer, Image.new("RGBA", img.size, (0, 0, 0, 0)), expanded)
    out.alpha_composite(img)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_lut_per_channel(img: Image.Image, lut: list[int]) -> Image.Image:
    if img.mode == "RGBA":
        r, g, b, a = img.split()
        r = r.point(lut)
        g = g.point(lut)
        b = b.point(lut)
        return Image.merge("RGBA", (r, g, b, a))
    if img.mode == "L":
        return img.point(lut)
    rgb = img.convert("RGB")
    r, g, b = rgb.split()
    return Image.merge("RGB", (r.point(lut), g.point(lut), b.point(lut)))


class _LCG:
    """Deterministic LCG for noise; cheap, no numpy."""

    def __init__(self, seed: int) -> None:
        self.state = seed & 0xFFFFFFFF or 1

    def next_unsigned(self) -> int:
        self.state = (1103515245 * self.state + 12345) & 0x7FFFFFFF
        return self.state

    def next_signed(self, bound: int) -> int:
        if bound <= 0:
            return 0
        v = self.next_unsigned() % (2 * bound + 1)
        return v - bound


_DISPATCH: dict[EffectKind, "EffectHandler"] = {
    EffectKind.BRIGHTNESS: _brightness,
    EffectKind.CONTRAST: _contrast,
    EffectKind.SATURATION: _saturation,
    EffectKind.HUE_SHIFT: _hue_shift,
    EffectKind.EXPOSURE: _exposure,
    EffectKind.GAMMA: _gamma,
    EffectKind.INVERT: _invert,
    EffectKind.GAUSSIAN_BLUR: _gaussian_blur,
    EffectKind.SHARPEN: _sharpen,
    EffectKind.UNSHARP_MASK: _unsharp_mask,
    EffectKind.NOISE_ADD: _noise_add,
    EffectKind.VIGNETTE: _vignette,
    EffectKind.PIXELATE: _pixelate,
    EffectKind.STROKE: _stroke,
}
