"""Charts + tables (spec §12) — minimum viable subset.

Produces deterministic Vega-Lite specs from a small `ChartSpec` dataclass.
The actual SVG render goes through `vl-convert-python` in production; the
in-memory implementation produces the JSON spec directly so callers can
test data validation, brand-kit palette injection, and CSV-injection
sanitisation without the renderer dep.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from stronghold.types.errors import (
    ChartSpecError,
    CSVInjectionError,
)

if TYPE_CHECKING:
    from stronghold.types.canvas_design import Color


class ChartKind(StrEnum):
    BAR = "bar"
    COLUMN = "column"
    STACKED_BAR = "stacked_bar"
    LINE = "line"
    AREA = "area"
    PIE = "pie"
    DONUT = "donut"
    SCATTER = "scatter"
    HEATMAP = "heatmap"


class ChannelType(StrEnum):
    QUANTITATIVE = "quantitative"
    NOMINAL = "nominal"
    ORDINAL = "ordinal"
    TEMPORAL = "temporal"


@dataclass(frozen=True)
class ChartChannel:
    field: str
    type: ChannelType


@dataclass(frozen=True)
class ChartEncoding:
    x: ChartChannel
    y: ChartChannel
    color: ChartChannel | None = None


@dataclass(frozen=True)
class ChartStyle:
    palette: tuple[Color, ...] = ()
    font_family: str = "Inter"
    font_size: int = 12
    background: Color | None = None


@dataclass(frozen=True)
class ChartSpec:
    kind: ChartKind
    rows: tuple[dict[str, Any], ...]
    encoding: ChartEncoding
    style: ChartStyle = field(default_factory=ChartStyle)
    size_px: tuple[int, int] = (800, 600)
    title: str | None = None


# ---------------------------------------------------------------------------
# CSV injection sanitisation
# ---------------------------------------------------------------------------


_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def sanitise_cell(value: Any) -> Any:
    """Strip Excel-style formula prefixes from string cells. Non-strings
    pass through unchanged."""
    if not isinstance(value, str):
        return value
    if value and value[0] in _INJECTION_PREFIXES:
        # Leading apostrophe escape (the convention Excel uses)
        return f"'{value}"
    return value


def sanitise_rows(rows: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({k: sanitise_cell(v) for k, v in row.items()})
    return tuple(out)


_PII_PATTERNS = (
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),  # emails
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN-style
    re.compile(r"\b\d{16}\b"),  # 16-digit credit card
)


def detect_pii(rows: tuple[dict[str, Any], ...]) -> list[tuple[str, int]]:
    """Return list of (field_name, row_index) where PII is found."""
    findings: list[tuple[str, int]] = []
    for i, row in enumerate(rows):
        for k, v in row.items():
            if not isinstance(v, str):
                continue
            for pattern in _PII_PATTERNS:
                if pattern.search(v):
                    findings.append((k, i))
                    break
    return findings


def assert_csv_safe(rows: tuple[dict[str, Any], ...], *, allow_pii: bool = False) -> None:
    """Raise CSVInjectionError on formula-injection or PII (unless allowed)."""
    for row in rows:
        for v in row.values():
            if isinstance(v, str) and v and v[0] in _INJECTION_PREFIXES:
                raise CSVInjectionError(
                    f"cell value {v[:32]!r}... starts with formula char {v[0]!r}"
                )
    if not allow_pii and detect_pii(rows):
        raise CSVInjectionError("rows contain PII; redact before importing")


# ---------------------------------------------------------------------------
# Vega-Lite spec render
# ---------------------------------------------------------------------------


def to_vega_lite(spec: ChartSpec) -> dict[str, Any]:
    """Build a Vega-Lite v5 spec dict from a ChartSpec.

    Production renders this via `vl-convert.vegalite_to_svg`.
    """
    if not spec.rows:
        empty_spec: dict[str, Any] = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": spec.title or "No data",
            "width": spec.size_px[0],
            "height": spec.size_px[1],
        }
        return empty_spec
    if spec.kind is ChartKind.PIE and any(
        not isinstance(row.get(spec.encoding.y.field, 0), int | float)
        or row.get(spec.encoding.y.field, 0) < 0
        for row in spec.rows
    ):
        raise ChartSpecError("PIE charts require non-negative numeric y values")

    fields_in_data = set(spec.rows[0].keys())
    referenced = {spec.encoding.x.field, spec.encoding.y.field}
    if spec.encoding.color is not None:
        referenced.add(spec.encoding.color.field)
    missing = referenced - fields_in_data
    if missing:
        raise ChartSpecError(f"encoding fields not in data: {sorted(missing)}")

    encoding: dict[str, Any] = {
        "x": {"field": spec.encoding.x.field, "type": spec.encoding.x.type.value},
        "y": {"field": spec.encoding.y.field, "type": spec.encoding.y.type.value},
    }
    if spec.encoding.color is not None:
        encoding["color"] = {
            "field": spec.encoding.color.field,
            "type": spec.encoding.color.type.value,
        }
        if spec.style.palette:
            encoding["color"]["scale"] = {"range": [c.value for c in spec.style.palette]}

    mark = _mark_for(spec.kind)
    out: dict[str, Any] = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": list(spec.rows)},
        "mark": mark,
        "encoding": encoding,
        "width": spec.size_px[0],
        "height": spec.size_px[1],
        "config": {
            "font": spec.style.font_family,
        },
    }
    if spec.title is not None:
        out["title"] = spec.title
    if spec.style.background is not None:
        out.setdefault("config", {})["background"] = spec.style.background.value
    return out


def to_vega_lite_json(spec: ChartSpec) -> str:
    return json.dumps(to_vega_lite(spec), separators=(",", ":"))


def _mark_for(kind: ChartKind) -> str:
    return {
        ChartKind.BAR: "bar",
        ChartKind.COLUMN: "bar",
        ChartKind.STACKED_BAR: "bar",
        ChartKind.LINE: "line",
        ChartKind.AREA: "area",
        ChartKind.PIE: "arc",
        ChartKind.DONUT: "arc",
        ChartKind.SCATTER: "point",
        ChartKind.HEATMAP: "rect",
    }[kind]


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableColumn:
    key: str
    header: str
    align: str = "left"  # left | right | center


@dataclass(frozen=True)
class TableSpec:
    columns: tuple[TableColumn, ...]
    rows: tuple[dict[str, Any], ...]
    banded: bool = True


def render_table_text(spec: TableSpec) -> str:
    """Render a table as a fixed-width text block. Production uses Pillow
    layout; this in-memory form is enough for snapshot testing."""
    widths = {col.key: max(len(col.header), 4) for col in spec.columns}
    for row in spec.rows:
        for col in spec.columns:
            cell = str(row.get(col.key, ""))
            widths[col.key] = max(widths[col.key], len(cell))
    lines = [" | ".join(col.header.ljust(widths[col.key]) for col in spec.columns)]
    lines.append("-+-".join("-" * widths[col.key] for col in spec.columns))
    for row in spec.rows:
        lines.append(
            " | ".join(str(row.get(col.key, "")).ljust(widths[col.key]) for col in spec.columns)
        )
    return "\n".join(lines)
