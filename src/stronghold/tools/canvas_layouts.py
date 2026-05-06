"""Book + page layouts (spec §10).

Per-`LayoutKind` slot definitions with bbox math, plus `layout_apply`
which positions an existing Page's layers into slot bboxes by `slot_id`,
or creates placeholder layers for missing required slots.

Pure-data: no Pillow, no LLM. All numerics are computed from the page's
trim_size + safe_area at apply time, so layouts adapt automatically to
different print specs.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from stronghold.types.canvas_design import (
    BBox,
    Color,
    Layer,
    LayerSourceKind,
    LayerTransform,
    LayoutKind,
    Page,
    RasterSource,
    ShapeKind,
    ShapeSource,
    TextSource,
)

# ---------------------------------------------------------------------------
# Slot definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LayoutSlot:
    """One named region inside a layout."""

    slot_id: str
    layer_kind: LayerSourceKind
    fraction: tuple[float, float, float, float]
    """`(x, y, w, h)` as fractions of the page trim. Computed against the
    page's trim_size at apply-time."""
    required: bool = True
    description: str = ""

    def bbox_in(self, trim_size: tuple[int, int]) -> BBox:
        w, h = trim_size
        return BBox(
            x=int(round(self.fraction[0] * w)),
            y=int(round(self.fraction[1] * h)),
            width=int(round(self.fraction[2] * w)),
            height=int(round(self.fraction[3] * h)),
        )


@dataclass(frozen=True)
class Layout:
    kind: LayoutKind
    slots: tuple[LayoutSlot, ...]


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------


def _full_bleed() -> Layout:
    return Layout(
        kind=LayoutKind.FULL_BLEED,
        slots=(
            LayoutSlot(
                slot_id="art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.0, 0.0, 1.0, 1.0),
                description="Full-page art covering bleed.",
            ),
        ),
    )


def _art_with_caption() -> Layout:
    return Layout(
        kind=LayoutKind.ART_WITH_CAPTION,
        slots=(
            LayoutSlot(
                slot_id="art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.0, 0.0, 1.0, 0.66),
            ),
            LayoutSlot(
                slot_id="caption",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.05, 0.7, 0.9, 0.25),
            ),
        ),
    )


def _art_with_body() -> Layout:
    return Layout(
        kind=LayoutKind.ART_WITH_BODY,
        slots=(
            LayoutSlot(
                slot_id="art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.0, 0.0, 1.0, 0.5),
            ),
            LayoutSlot(
                slot_id="body",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.05, 0.55, 0.9, 0.4),
            ),
        ),
    )


def _double_spread() -> Layout:
    return Layout(
        kind=LayoutKind.DOUBLE_SPREAD,
        slots=(
            LayoutSlot(
                slot_id="art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.0, 0.0, 1.0, 1.0),
            ),
        ),
    )


def _text_only() -> Layout:
    return Layout(
        kind=LayoutKind.TEXT_ONLY,
        slots=(
            LayoutSlot(
                slot_id="body",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.1, 0.8, 0.8),
            ),
        ),
    )


def _vignette() -> Layout:
    return Layout(
        kind=LayoutKind.VIGNETTE,
        slots=(
            LayoutSlot(
                slot_id="art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.05, 0.05, 0.4, 0.4),
            ),
            LayoutSlot(
                slot_id="body",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.05, 0.5, 0.9, 0.45),
            ),
        ),
    )


def _cover() -> Layout:
    return Layout(
        kind=LayoutKind.COVER,
        slots=(
            LayoutSlot(
                slot_id="hero_art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.0, 0.0, 1.0, 1.0),
                description="Hero illustration covering the full cover.",
            ),
            LayoutSlot(
                slot_id="title",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.7, 0.8, 0.15),
            ),
            LayoutSlot(
                slot_id="subtitle",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.85, 0.8, 0.05),
                required=False,
            ),
            LayoutSlot(
                slot_id="byline",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.92, 0.8, 0.05),
            ),
        ),
    )


def _title_page() -> Layout:
    return Layout(
        kind=LayoutKind.TITLE_PAGE,
        slots=(
            LayoutSlot(
                slot_id="title",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.4, 0.8, 0.15),
            ),
            LayoutSlot(
                slot_id="subtitle",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.55, 0.8, 0.05),
                required=False,
            ),
            LayoutSlot(
                slot_id="byline",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.7, 0.8, 0.05),
            ),
        ),
    )


def _copyright_page() -> Layout:
    return Layout(
        kind=LayoutKind.COPYRIGHT_PAGE,
        slots=(
            LayoutSlot(
                slot_id="copyright",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.5, 0.8, 0.4),
            ),
        ),
    )


def _dedication() -> Layout:
    return Layout(
        kind=LayoutKind.DEDICATION_PAGE,
        slots=(
            LayoutSlot(
                slot_id="dedication",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.2, 0.4, 0.6, 0.2),
            ),
        ),
    )


def _poster() -> Layout:
    return Layout(
        kind=LayoutKind.POSTER,
        slots=(
            LayoutSlot(
                slot_id="hero_art",
                layer_kind=LayerSourceKind.RASTER,
                fraction=(0.0, 0.0, 1.0, 1.0),
            ),
            LayoutSlot(
                slot_id="title",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.7, 0.8, 0.15),
            ),
            LayoutSlot(
                slot_id="cta",
                layer_kind=LayerSourceKind.TEXT,
                fraction=(0.1, 0.88, 0.8, 0.07),
                required=False,
            ),
        ),
    )


def _infographic_grid() -> Layout:
    return Layout(
        kind=LayoutKind.INFOGRAPHIC_GRID,
        slots=tuple(
            LayoutSlot(
                slot_id=f"cell_{r}_{c}",
                layer_kind=LayerSourceKind.GROUP,
                fraction=(c * 0.5, r * 0.5, 0.5, 0.5),
                required=False,
            )
            for r in range(2)
            for c in range(2)
        ),
    )


def _infographic_flow() -> Layout:
    return Layout(
        kind=LayoutKind.INFOGRAPHIC_FLOW,
        slots=tuple(
            LayoutSlot(
                slot_id=f"section_{i}",
                layer_kind=LayerSourceKind.GROUP,
                fraction=(0.05, 0.05 + i * 0.3, 0.9, 0.25),
                required=False,
            )
            for i in range(3)
        ),
    )


_CATALOGUE: dict[LayoutKind, Layout] = {
    LayoutKind.FULL_BLEED: _full_bleed(),
    LayoutKind.ART_WITH_CAPTION: _art_with_caption(),
    LayoutKind.ART_WITH_BODY: _art_with_body(),
    LayoutKind.DOUBLE_SPREAD: _double_spread(),
    LayoutKind.TEXT_ONLY: _text_only(),
    LayoutKind.VIGNETTE: _vignette(),
    LayoutKind.COVER: _cover(),
    LayoutKind.TITLE_PAGE: _title_page(),
    LayoutKind.COPYRIGHT_PAGE: _copyright_page(),
    LayoutKind.DEDICATION_PAGE: _dedication(),
    LayoutKind.POSTER: _poster(),
    LayoutKind.INFOGRAPHIC_GRID: _infographic_grid(),
    LayoutKind.INFOGRAPHIC_FLOW: _infographic_flow(),
}


def get_layout(kind: LayoutKind) -> Layout:
    return _CATALOGUE[kind]


def list_layouts() -> tuple[LayoutKind, ...]:
    return tuple(_CATALOGUE.keys())


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def layout_apply(page: Page, kind: LayoutKind) -> Page:
    """Position existing slot-tagged layers; create placeholders for required
    slots that have no matching layer.

    Returns a new Page with layout_kind set + layers re-positioned/created.
    Non-slot layers (those without matching slot_id) are preserved as
    "free" layers — kept on the page but not repositioned.
    """
    layout = _CATALOGUE[kind]
    existing_by_slot = {layer.slot_id: layer for layer in page.layers if layer.slot_id is not None}
    free_layers = [layer for layer in page.layers if layer.slot_id is None]
    new_layers: list[Layer] = list(free_layers)

    for slot in layout.slots:
        bbox = slot.bbox_in(page.print_spec.trim_size)
        existing = existing_by_slot.get(slot.slot_id)
        if existing is not None:
            new_layers.append(_reposition(existing, bbox))
            continue
        if slot.required:
            new_layers.append(_placeholder_for(slot, bbox))

    return dataclasses.replace(
        page,
        layers=tuple(new_layers),
        layout_kind=kind,
    )


def auto_paginate_word_count(
    text: str,
    *,
    age_band: str,
) -> int:
    """How many pages does `text` need at the given age-band density?

    Words-per-page targets (spec §10):
      AGE_5_7  → 60 wpp
      AGE_7_9  → 90 wpp
      AGE_9_12 → 250 wpp
      else     → 60 wpp default
    """
    wpp = {
        "5_7": 60,
        "7_9": 90,
        "9_12": 250,
    }.get(age_band, 60)
    words = max(1, len(text.split()))
    return max(1, (words + wpp - 1) // wpp)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reposition(layer: Layer, bbox: BBox) -> Layer:
    return dataclasses.replace(
        layer,
        transform=dataclasses.replace(
            layer.transform,
            x=bbox.x,
            y=bbox.y,
        ),
    )


def _placeholder_for(slot: LayoutSlot, bbox: BBox) -> Layer:
    source: TextSource | RasterSource | ShapeSource
    if slot.layer_kind is LayerSourceKind.TEXT:
        source = TextSource(content=f"<{slot.slot_id}>")
    elif slot.layer_kind is LayerSourceKind.RASTER:
        source = RasterSource(
            blob_id="",
            width=bbox.width,
            height=bbox.height,
        )
    else:
        # Group / shape placeholders — use a simple rectangle marker
        source = ShapeSource(
            shape_kind=ShapeKind.RECTANGLE,
            geometry={"width": bbox.width, "height": bbox.height},
            fill={"kind": "solid", "color": Color("#EEEEEE")},
        )
    return Layer(
        id=f"placeholder-{slot.slot_id}",
        name=slot.slot_id,
        source=source,
        transform=LayerTransform(x=bbox.x, y=bbox.y),
        slot_id=slot.slot_id,
        placeholder_slot=slot.slot_id,
        z_index=0,
    )


# ---------------------------------------------------------------------------
# Per-DocumentKind defaults (spec §10)
# ---------------------------------------------------------------------------


_PICTURE_BOOK_DEFAULTS: tuple[LayoutKind, ...] = (
    LayoutKind.COVER,
    LayoutKind.TITLE_PAGE,
    LayoutKind.COPYRIGHT_PAGE,
    LayoutKind.DEDICATION_PAGE,
    LayoutKind.ART_WITH_CAPTION,
    LayoutKind.ART_WITH_CAPTION,
)


def picture_book_default_layout(page_index: int, total_pages: int) -> LayoutKind:
    if page_index == 0:
        return LayoutKind.COVER
    if page_index == 1:
        return LayoutKind.TITLE_PAGE
    if page_index == 2:
        return LayoutKind.COPYRIGHT_PAGE
    if page_index == 3:
        return LayoutKind.DEDICATION_PAGE
    if page_index == total_pages - 1:
        return LayoutKind.BACK_MATTER
    return LayoutKind.ART_WITH_CAPTION


def early_reader_default_layout(page_index: int) -> LayoutKind:
    if page_index == 0:
        return LayoutKind.COVER
    if page_index == 1:
        return LayoutKind.TITLE_PAGE
    if page_index == 2:
        return LayoutKind.COPYRIGHT_PAGE
    return LayoutKind.ART_WITH_BODY
