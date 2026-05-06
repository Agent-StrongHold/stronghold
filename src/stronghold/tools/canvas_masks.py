"""Mask generation + composition (spec §03).

`PillowMaskGenerator` implements the `MaskGenerator` Protocol for the
shape-driven origins that need no external models:

  - BBOX: rectangular mask
  - POLYGON: vertex-list polygon (auto-corrected via Pillow)
  - BRUSH: composition of N circular dabs
  - UPLOADED: normalise an L-mode PNG to canonical form

`AUTO_SUBJECT` / `AUTO_BACKGROUND` / `PROMPT` origins require external
models (rembg / SAM-2) and are deferred — this module raises
`MaskBackendError` when those are requested.

`combine(op, masks)` implements per-pixel boolean ops via Pillow's
`ImageChops`: union, intersect, subtract, invert.
"""

from __future__ import annotations

import io
import math
import uuid
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageChops, ImageDraw

from stronghold.types.canvas_design import Mask, MaskOrigin
from stronghold.types.errors import (
    MaskBackendError,
    MaskParamsError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


_DEFAULT_DIMS = (512, 512)
_BRUSH_MAX_DABS = 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id() -> str:
    return str(uuid.uuid4())


def _to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.convert("L").save(buf, format="PNG")
    return buf.getvalue()


def _from_png_bytes(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img.convert("L")


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class PillowMaskGenerator:
    """In-process mask generator for shape-driven origins."""

    async def create(
        self,
        origin: MaskOrigin,
        *,
        layer_id: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Mask:
        params = params or {}
        if origin is MaskOrigin.BBOX:
            return self._bbox(params)
        if origin is MaskOrigin.POLYGON:
            return self._polygon(params)
        if origin is MaskOrigin.BRUSH:
            return self._brush(params)
        if origin is MaskOrigin.UPLOADED:
            return self._uploaded(params)
        if origin in (
            MaskOrigin.AUTO_SUBJECT,
            MaskOrigin.AUTO_BACKGROUND,
            MaskOrigin.PROMPT,
        ):
            raise MaskBackendError(
                f"PillowMaskGenerator cannot satisfy origin={origin.value}; "
                "requires rembg / SAM-2 backend"
            )
        raise MaskParamsError(f"Unknown mask origin: {origin}")

    def combine(self, op: str, masks: Sequence[Mask]) -> Mask:
        if not masks:
            raise MaskParamsError("combine requires at least one input mask")
        if op == "invert":
            if len(masks) != 1:
                raise MaskParamsError("invert takes exactly one mask")
            inverted = ImageChops.invert(_from_png_bytes(masks[0].data))
            return Mask(
                id=_new_id(),
                width=masks[0].width,
                height=masks[0].height,
                data=_to_png_bytes(inverted),
                origin=masks[0].origin,
                metadata={"derived_via": "invert"},
            )
        if len(masks) < 2:
            raise MaskParamsError(f"op={op!r} requires at least 2 masks")
        # All masks must agree on dims for boolean ops
        first = masks[0]
        for m in masks[1:]:
            if (m.width, m.height) != (first.width, first.height):
                raise MaskParamsError(
                    "combine masks must share dimensions; got "
                    f"{first.width}x{first.height} vs {m.width}x{m.height}"
                )
        images = [_from_png_bytes(m.data) for m in masks]
        out = images[0]
        if op == "union":
            for img in images[1:]:
                out = ImageChops.lighter(out, img)  # max per pixel
        elif op == "intersect":
            for img in images[1:]:
                out = ImageChops.darker(out, img)  # min per pixel
        elif op == "subtract":
            # subtract(a, b) = max(0, a - b); commutativity NOT preserved
            for img in images[1:]:
                out = ImageChops.subtract(out, img)
        else:
            raise MaskParamsError(f"Unknown combine op: {op!r}")
        return Mask(
            id=_new_id(),
            width=first.width,
            height=first.height,
            data=_to_png_bytes(out),
            origin=first.origin,
            metadata={"derived_via": op, "input_count": len(masks)},
        )

    # ── per-origin implementations ──────────────────────────────────────

    def _bbox(self, params: dict[str, Any]) -> Mask:
        width, height = _dims_from_params(params)
        bbox = params.get("bbox")
        if bbox is None or not isinstance(bbox, tuple | list) or len(bbox) != 4:
            raise MaskParamsError("BBOX origin requires params['bbox'] as (x1, y1, x2, y2)")
        x1, y1, x2, y2 = (int(v) for v in bbox)
        if x1 >= x2 or y1 >= y2:
            raise MaskParamsError(f"BBOX coords malformed: {bbox}")
        canvas = Image.new("L", (width, height), color=0)
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((x1, y1, x2, y2), fill=255)
        return Mask(
            id=_new_id(),
            width=width,
            height=height,
            data=_to_png_bytes(canvas),
            origin=MaskOrigin.BBOX,
            feather=int(params.get("feather", 0)),
            invert=bool(params.get("invert", False)),
            metadata={"bbox": list(bbox)},
        )

    def _polygon(self, params: dict[str, Any]) -> Mask:
        width, height = _dims_from_params(params)
        vertices = params.get("vertices")
        if not isinstance(vertices, list | tuple) or len(vertices) < 3:
            raise MaskParamsError("POLYGON origin requires params['vertices'] with >= 3 points")
        normalised = [(int(x), int(y)) for x, y in vertices]
        # Reject collinear/zero-area polygons
        if _polygon_area(normalised) < 0.5:
            raise MaskParamsError("POLYGON has zero (or near-zero) area")
        canvas = Image.new("L", (width, height), color=0)
        draw = ImageDraw.Draw(canvas)
        draw.polygon(normalised, fill=255)
        return Mask(
            id=_new_id(),
            width=width,
            height=height,
            data=_to_png_bytes(canvas),
            origin=MaskOrigin.POLYGON,
            feather=int(params.get("feather", 0)),
            invert=bool(params.get("invert", False)),
            metadata={"vertices": [list(v) for v in normalised]},
        )

    def _brush(self, params: dict[str, Any]) -> Mask:
        width, height = _dims_from_params(params)
        dabs = params.get("dabs")
        if not isinstance(dabs, list | tuple):
            raise MaskParamsError("BRUSH origin requires params['dabs'] as list of (x, y, radius)")
        if len(dabs) > _BRUSH_MAX_DABS:
            raise MaskParamsError(f"BRUSH dab count {len(dabs)} exceeds limit {_BRUSH_MAX_DABS}")
        canvas = Image.new("L", (width, height), color=0)
        draw = ImageDraw.Draw(canvas)
        for dab in dabs:
            if len(dab) != 3:
                raise MaskParamsError(f"BRUSH dab must be (x, y, radius); got {dab}")
            x, y, r = (float(v) for v in dab)
            if r <= 0:
                raise MaskParamsError(f"BRUSH dab radius must be > 0; got {r}")
            draw.ellipse((x - r, y - r, x + r, y + r), fill=255)
        return Mask(
            id=_new_id(),
            width=width,
            height=height,
            data=_to_png_bytes(canvas),
            origin=MaskOrigin.BRUSH,
            feather=int(params.get("feather", 0)),
            invert=bool(params.get("invert", False)),
            metadata={"dab_count": len(dabs)},
        )

    def _uploaded(self, params: dict[str, Any]) -> Mask:
        data = params.get("data")
        if not isinstance(data, bytes | bytearray):
            raise MaskParamsError("UPLOADED origin requires params['data'] as bytes")
        target_dims = params.get("target_dims")
        auto_resize = bool(params.get("auto_resize", True))
        opened = Image.open(io.BytesIO(bytes(data)))
        opened.load()
        # Always normalise to L
        img: Image.Image = opened.convert("L")
        if target_dims is not None:
            tw, th = (int(v) for v in target_dims)
            if (img.width, img.height) != (tw, th):
                if not auto_resize:
                    raise MaskParamsError(
                        f"uploaded mask {img.width}x{img.height} != target {tw}x{th}"
                    )
                img = img.resize((tw, th), Image.Resampling.BILINEAR)
        return Mask(
            id=_new_id(),
            width=img.width,
            height=img.height,
            data=_to_png_bytes(img),
            origin=MaskOrigin.UPLOADED,
            feather=int(params.get("feather", 0)),
            invert=bool(params.get("invert", False)),
            metadata={"normalised": True},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dims_from_params(params: dict[str, Any]) -> tuple[int, int]:
    dims = params.get("dims") or _DEFAULT_DIMS
    if not isinstance(dims, list | tuple) or len(dims) != 2:
        raise MaskParamsError("dims must be (width, height)")
    w, h = int(dims[0]), int(dims[1])
    if w <= 0 or h <= 0:
        raise MaskParamsError(f"dims must be positive, got {w}x{h}")
    return w, h


def _polygon_area(vertices: Sequence[tuple[int, int]]) -> float:
    """Shoelace formula for polygon area; absolute value."""
    n = len(vertices)
    total = 0.0
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return math.fabs(total) / 2.0
