"""Smart resize (spec §14).

Re-layout a Page into a different aspect ratio while preserving subject
framing, text reflow, and brand consistency. The actual generative
re-render is delegated; this module does the layer-classification +
target-bbox arithmetic.

The four strategies:
  STRETCH               — naive scale (last resort)
  CROP_TO_SUBJECT       — frame around the subject
  REFLOW                — re-position layers per role rules
  REGENERATE_BACKGROUND — outpaint or regen background to fill new bbox
  SMART_AUTO            — combine strategies based on layer roles
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import StrEnum

from stronghold.types.canvas_design import (
    BBox,
    GroupSource,
    Layer,
    Page,
    PrintSpec,
    RasterSource,
    ShapeSource,
    TextSource,
)
from stronghold.types.errors import (
    SmartResizeTargetInvalidError,
    SmartResizeTextOverflowError,
)


class ResizeStrategy(StrEnum):
    STRETCH = "stretch"
    CROP_TO_SUBJECT = "crop_to_subject"
    REFLOW = "reflow"
    REGENERATE_BACKGROUND = "regenerate_background"
    SMART_AUTO = "smart_auto"


_TEXT_SHRINK_LIMIT = 0.30  # 30% per spec §14
_BG_REGEN_ASPECT_DELTA = 0.20  # > 20% aspect change → regen rather than outpaint
_LOGO_MIN_PX = 24


@dataclass(frozen=True)
class ResizeReport:
    """Per-call summary of which strategies fired + which warnings."""

    target_size_px: tuple[int, int]
    strategy_used: ResizeStrategy
    aspect_delta: float
    bg_action: str  # "outpaint" | "regenerate" | "stretch" | "skip"
    text_shrunk_pct: float
    warnings: tuple[str, ...] = ()


def smart_resize(
    page: Page,
    target_size_px: tuple[int, int],
    *,
    strategy: ResizeStrategy = ResizeStrategy.SMART_AUTO,
) -> tuple[Page, ResizeReport]:
    target_w, target_h = target_size_px
    if target_w <= 0 or target_h <= 0:
        raise SmartResizeTargetInvalidError(f"target dims must be positive, got {target_size_px}")
    src_w, src_h = page.print_spec.trim_size
    src_aspect = src_w / src_h
    target_aspect = target_w / target_h
    aspect_delta = abs(target_aspect - src_aspect) / src_aspect

    # Idempotent on identical dims
    if (src_w, src_h) == (target_w, target_h):
        return page, ResizeReport(
            target_size_px=target_size_px,
            strategy_used=strategy,
            aspect_delta=0.0,
            bg_action="skip",
            text_shrunk_pct=0.0,
        )

    chosen = strategy
    warnings: list[str] = []
    if strategy is ResizeStrategy.SMART_AUTO:
        if aspect_delta < 0.05:
            chosen = ResizeStrategy.REFLOW
        elif aspect_delta < _BG_REGEN_ASPECT_DELTA:
            chosen = ResizeStrategy.REGENERATE_BACKGROUND
            warnings.append("aspect_change_mild_outpaint_used")
        else:
            chosen = ResizeStrategy.REGENERATE_BACKGROUND
            warnings.append("aspect_change_dramatic_full_regen")
    elif strategy is ResizeStrategy.STRETCH and aspect_delta > 0.20:
        warnings.append("stretch_may_distort")

    bg_action = _bg_action_for(chosen, aspect_delta)
    new_layers, text_shrunk_pct, more_warnings = _retransform_layers(
        page.layers,
        src_size=(src_w, src_h),
        target_size=target_size_px,
        bg_action=bg_action,
    )
    warnings.extend(more_warnings)

    new_spec = PrintSpec(
        trim_size=target_size_px,
        dpi=page.print_spec.dpi,
        bleed=page.print_spec.bleed,
        safe_area=page.print_spec.safe_area,
        color_mode=page.print_spec.color_mode,
        icc_profile=page.print_spec.icc_profile,
        binding=page.print_spec.binding,
    )
    return (
        dataclasses.replace(page, print_spec=new_spec, layers=tuple(new_layers)),
        ResizeReport(
            target_size_px=target_size_px,
            strategy_used=chosen,
            aspect_delta=aspect_delta,
            bg_action=bg_action,
            text_shrunk_pct=text_shrunk_pct,
            warnings=tuple(warnings),
        ),
    )


def smart_resize_batch(
    page: Page,
    targets: tuple[tuple[int, int], ...],
    *,
    strategy: ResizeStrategy = ResizeStrategy.SMART_AUTO,
) -> list[tuple[Page, ResizeReport]]:
    return [smart_resize(page, target, strategy=strategy) for target in targets]


# ---------------------------------------------------------------------------
# Standard target sets
# ---------------------------------------------------------------------------


SOCIAL_KIT: tuple[tuple[int, int], ...] = (
    (1080, 1080),  # IG square
    (1080, 1920),  # IG story / TikTok
    (1640, 856),  # FB cover
    (1584, 396),  # LinkedIn header
    (1200, 675),  # X post
)


PRINT_KIT: tuple[tuple[int, int], ...] = (
    (4961, 7016),  # A2
    (3508, 4961),  # A3
    (2480, 3508),  # A4
    (2550, 3300),  # US Letter
    (3300, 5100),  # Tabloid
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bg_action_for(strategy: ResizeStrategy, aspect_delta: float) -> str:
    if strategy is ResizeStrategy.REGENERATE_BACKGROUND:
        return "regenerate" if aspect_delta >= _BG_REGEN_ASPECT_DELTA else "outpaint"
    if strategy is ResizeStrategy.STRETCH:
        return "stretch"
    if strategy is ResizeStrategy.REFLOW:
        return "skip"
    return "skip"


def _classify(layer: Layer) -> str:
    """Bucket a layer by role for the resize decision."""
    src = layer.source
    if isinstance(src, RasterSource):
        if layer.metadata.get("role") == "logo":
            return "logo"
        if layer.slot_id and "hero" in layer.slot_id:
            return "subject"
        return "background"
    if isinstance(src, TextSource):
        return "text"
    if isinstance(src, ShapeSource):
        return "decoration"
    if isinstance(src, GroupSource):
        return "group"
    return "other"


def _retransform_layers(
    layers: tuple[Layer, ...],
    *,
    src_size: tuple[int, int],
    target_size: tuple[int, int],
    bg_action: str,
) -> tuple[list[Layer], float, list[str]]:
    src_w, src_h = src_size
    target_w, target_h = target_size
    sx = target_w / src_w
    sy = target_h / src_h
    text_shrunk_pct = 0.0
    warnings: list[str] = []
    out: list[Layer] = []
    multi_subject = sum(1 for layer in layers if _classify(layer) == "subject") > 1
    if multi_subject and target_w < src_w * 0.8:
        warnings.append("multiple_subjects_in_narrow_target")

    for layer in layers:
        role = _classify(layer)
        if role == "logo":
            out.append(_reposition_logo(layer, src_size, target_size, warnings))
        elif role == "subject":
            out.append(_centre_subject(layer, src_size, target_size))
        elif role == "background":
            out.append(_resize_bg(layer, sx, sy, action=bg_action))
        elif role == "text":
            new_layer, this_pct, this_warn = _reflow_text(layer, sx, sy)
            text_shrunk_pct = max(text_shrunk_pct, this_pct)
            warnings.extend(this_warn)
            out.append(new_layer)
        else:
            # decoration/other — uniform scale
            scale = min(sx, sy)
            out.append(
                dataclasses.replace(
                    layer,
                    transform=dataclasses.replace(
                        layer.transform,
                        x=int(round(layer.transform.x * sx)),
                        y=int(round(layer.transform.y * sy)),
                        scale=layer.transform.scale * scale,
                    ),
                )
            )
    return out, text_shrunk_pct, warnings


def _reposition_logo(
    layer: Layer,
    src_size: tuple[int, int],
    target_size: tuple[int, int],
    warnings: list[str],
) -> Layer:
    """Pin a logo to its current corner; downscale to keep ≥ _LOGO_MIN_PX."""
    src_w, src_h = src_size
    target_w, target_h = target_size
    src = layer.source
    assert isinstance(src, RasterSource)
    cur_x = layer.transform.x
    cur_y = layer.transform.y
    horizontal = "right" if cur_x > src_w / 2 else "left"
    vertical = "bottom" if cur_y > src_h / 2 else "top"
    # Choose a target scale so the logo doesn't grow disproportionately
    target_scale = min(target_w / src_w, target_h / src_h, layer.transform.scale)
    if src.width * target_scale < _LOGO_MIN_PX:
        target_scale = _LOGO_MIN_PX / max(1, src.width)
        warnings.append("logo_below_min_size_clamped")
    new_w = int(src.width * target_scale)
    new_h = int(src.height * target_scale)
    new_x = (target_w - new_w) if horizontal == "right" else 0
    new_y = (target_h - new_h) if vertical == "bottom" else 0
    return dataclasses.replace(
        layer,
        transform=dataclasses.replace(
            layer.transform,
            x=new_x,
            y=new_y,
            scale=target_scale,
        ),
    )


def _centre_subject(
    layer: Layer,
    src_size: tuple[int, int],
    target_size: tuple[int, int],
) -> Layer:
    """Centre the subject's bbox in the target. Preserves aspect by uniform scale."""
    src_w, src_h = src_size
    target_w, target_h = target_size
    src = layer.source
    if not isinstance(src, RasterSource) or src.width == 0 or src.height == 0:
        return layer
    scale = min(target_w / src_w, target_h / src_h, 1.0) * layer.transform.scale
    layer_w = int(src.width * scale)
    layer_h = int(src.height * scale)
    new_x = max(0, (target_w - layer_w) // 2)
    new_y = max(0, (target_h - layer_h) // 2)
    return dataclasses.replace(
        layer,
        transform=dataclasses.replace(
            layer.transform,
            x=new_x,
            y=new_y,
            scale=scale,
        ),
    )


def _resize_bg(layer: Layer, sx: float, sy: float, *, action: str) -> Layer:
    """Background: stretch / outpaint / regenerate. Outpaint and regenerate
    materialise as metadata flags here — the actual gen call is delegated."""
    metadata = dict(layer.metadata)
    if action != "skip":
        metadata["resize_action"] = action
    return dataclasses.replace(
        layer,
        transform=dataclasses.replace(
            layer.transform,
            x=int(round(layer.transform.x * sx)),
            y=int(round(layer.transform.y * sy)),
            scale=layer.transform.scale * max(sx, sy)
            if action == "stretch"
            else layer.transform.scale,
        ),
        metadata=metadata,
    )


def _reflow_text(layer: Layer, sx: float, sy: float) -> tuple[Layer, float, list[str]]:
    """Text reflow: scale font by min(sx, sy) clamped to ≥ 70% (spec §14).

    Returns (new_layer, percentage_shrunk_0_to_1, warnings).
    """
    text_warnings: list[str] = []
    src = layer.source
    if not isinstance(src, TextSource):
        return layer, 0.0, text_warnings
    target_scale = min(sx, sy)
    if target_scale < 1 - _TEXT_SHRINK_LIMIT:
        raise SmartResizeTextOverflowError(
            f"text shrink to {target_scale:.0%} exceeds 30% limit; "
            "shorten copy or increase target dims"
        )
    pct = max(0.0, 1 - target_scale)
    if pct > 0.10:
        text_warnings.append(f"text_shrunk_{int(pct * 100)}_pct")
    new_size = max(1, int(round(src.style.size_px * target_scale)))
    new_style = dataclasses.replace(src.style, size_px=new_size)
    new_source = dataclasses.replace(src, style=new_style)
    return (
        dataclasses.replace(
            layer,
            source=new_source,
            transform=dataclasses.replace(
                layer.transform,
                x=int(round(layer.transform.x * sx)),
                y=int(round(layer.transform.y * sy)),
            ),
        ),
        pct,
        text_warnings,
    )


# Unused but documented — bbox helpers might be needed by callers building
# layout-aware grids. Keeping them here avoids re-deriving in tests.


def fit_into(content: BBox, target: BBox, *, mode: str = "contain") -> BBox:
    """Cover/contain/fill a content bbox inside a target bbox."""
    if content.width == 0 or content.height == 0:
        return target
    cx = content.width / target.width
    cy = content.height / target.height
    if mode == "cover":
        scale = max(target.width / content.width, target.height / content.height)
    elif mode == "fill":
        scale = max(cx, cy)
    else:  # contain
        scale = min(target.width / content.width, target.height / content.height)
    new_w = int(content.width * scale)
    new_h = int(content.height * scale)
    return BBox(
        x=target.x + max(0, (target.width - new_w) // 2),
        y=target.y + max(0, (target.height - new_h) // 2),
        width=new_w,
        height=new_h,
    )
