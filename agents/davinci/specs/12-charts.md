# 12 — Charts, Tables, Connectors

**Status**: P0 (charts) / P1 (advanced viz). Infographic core.
**One-liner**: data-driven visual primitives — Vega-Lite charts, tables,
connectors — emitted as vector layers and composable on any page.

## Problem it solves

Infographics need *real* charts: a 5-bar chart should have correct axes, not
a blurry approximation of one. Tables need aligned cells. Connectors need
auto-routing. Generative tools can't be trusted with data — these primitives
are deterministic.

## Chart subsystem

```
ChartSpec (frozen):
  kind: ChartKind
  data: ChartData                  # rows or url-loaded
  encoding: ChartEncoding          # x, y, color, size mappings
  style: ChartStyle                # palette, fonts, axes, legend
  size_px: tuple[int, int]
  background: Color = "transparent"

ChartKind (StrEnum):
  BAR | COLUMN | STACKED_BAR | STACKED_COLUMN
  LINE | AREA | STACKED_AREA
  PIE | DONUT
  SCATTER | BUBBLE
  HEATMAP | SANKEY                  # P1
  CHOROPLETH                        # P2 (geopandas)

ChartData (tagged union):
  Inline:    {kind: "inline", rows: tuple[Mapping[str, Any], ...]}
  CSVUpload: {kind: "csv", blob_id: str}
  Query:     {kind: "query", source: "google_sheets" | "postgres" | "rest", config: Mapping[str, Any]}

ChartEncoding (frozen):
  x: ChartChannel
  y: ChartChannel
  color: ChartChannel | None = None
  size: ChartChannel | None = None
  tooltip: tuple[str, ...] = ()    # field names to include

ChartChannel (frozen):
  field: str
  type: ChannelType                # QUANTITATIVE | NOMINAL | ORDINAL | TEMPORAL
  title: str | None = None
  scale: ChartScale | None = None  # log, sqrt, etc.
  axis: AxisStyle | None = None    # gridlines, ticks, format

ChartStyle (frozen):
  palette: tuple[Color, ...]       # from brand kit by default
  font_family: str = "Inter"
  font_size: int = 12
  axis_color: Color = "#444"
  grid_color: Color = "#EEE"
  legend: LegendStyle              # POSITION + ORIENTATION
```

## Backend

Vega-Lite spec produced from `ChartSpec`, rendered to SVG via
`vl-convert-python` (Rust, no node.js dep, fast). The SVG becomes a `PATH`
shape layer (§06). Brand-kit palette is auto-injected.

```
def render_chart(spec: ChartSpec) -> ShapeSource:
    vega_spec = to_vega_lite(spec)
    svg = vl_convert.vegalite_to_svg(vega_spec)
    geometry = parse_svg_to_path_commands(svg)
    return ShapeSource(kind=PATH, geometry=geometry, ...)
```

## Tables

```
TableLayer (frozen):
  rows: tuple[TableRow, ...]
  columns: tuple[TableColumn, ...]
  style: TableStyle

TableRow:    {cells: tuple[TableCell, ...], height: int | None}
TableColumn: {width: int | None, alignment: Alignment, format: str | None}
TableCell:   {content: str, style_overrides: Mapping[str, Any]}

TableStyle:
  header_style: TextStyle
  body_style: TextStyle
  border_color: Color
  border_width: float
  banded_rows: bool = False
  band_color: Color = "#F8F8F8"
  cell_padding: int = 8
```

Render: each cell is laid out as a text+rect layer; the table is a group.
Numeric columns auto-right-align; cells can override.

## Connectors (cross-ref §06 shapes)

Connectors live in §06; this spec adds the *infographic* use cases:

| Use | Implementation |
|---|---|
| Flowchart arrow | shape kind ARROW with orthogonal routing |
| Process step linkage | connector style=arrow, anchored to nearest edge |
| Hierarchy tree edge | line with bezier routing |
| Annotation pointer | callout (§06) shape with anchor + body |

Connectors recompute when endpoints move (§06 Edge case 4).

## Data sources

| Source | P-level | Mechanism |
|---|---|---|
| Inline JSON/CSV | P0 | `data.rows` literal in spec |
| CSV upload | P0 | upload as blob, spec references blob_id |
| Google Sheets | P1 | OAuth + read API; rate-limited |
| Postgres / external SQL | P2 | tenant-configured connection; read-only role |
| REST endpoint | P2 | tenant-allow-listed URLs only; Warden scan response |

For P0, the agent helps users construct inline data via CSV upload. P1 adds
live data refresh (auto-rerender on change).

## Auto-styling from brand kit

When a Document has a BrandKit, charts inherit:
- `palette`: ordinal/nominal channels mapped to brand palette
- `font_family`: body font
- `font_size`: scaled to chart size

User can override per-chart.

## API surface

| Action | Args | Returns |
|---|---|---|
| `chart` | `kind, data, encoding, [style, size_px]` | new shape (PATH) layer |
| `chart_update` | `layer_id, fields` | replaced layer |
| `chart_data_update` | `layer_id, new_data` | re-rendered layer |
| `table` | `rows, columns, [style]` | new group layer |
| `connector` | `from_layer_id, to_layer_id, style, [routing]` | from §06 |

## Edge cases

1. **Empty data** — chart renders axes only with "No data" centred.
2. **Single data point in line/area** — render as a point marker; warn.
3. **Pie chart with 1 slice** — full circle; warn.
4. **More categories than palette colours** — cycle palette; warn.
5. **Field referenced in encoding not in data** — `ChartSpecError`.
6. **Negative values in pie/donut** — reject; pie requires non-negative.
7. **Quantitative axis with all-zero values** — auto-scale [-1..1].
8. **Temporal field with mixed formats** — best-effort parse via dateutil;
   warn on failure; ChartSpecError if failure rate > 50%.
9. **CSV with formula injection** (`=SUM(...)`) — Sentinel strips/escapes
   leading `=`, `+`, `-`, `@` per OWASP CSV injection guidance.
10. **Chart size too small for legend** — auto-hide legend with warning.
11. **Massive dataset** (> 100k rows) — sample or aggregate before render;
    surface to user.
12. **CSV with PII** — Warden flag; block storage; user must redact.

## Errors

- `ChartSpecError(ConfigError)` — invalid spec
- `ChartDataLoadError(ToolError)` — CSV parse failed, source unreachable
- `ChartRenderBackendError(ToolError)` — vl-convert failure
- `CSVInjectionError(SecurityError)` — formula injection attempted

## Test surface

- Unit: every ChartKind constructs a valid Vega-Lite spec; encoding
  validation; CSV injection sanitization.
- Golden: known data → known SVG (with tolerance for renderer version drift).
- Integration: chart inherits brand kit palette; chart_data_update
  re-renders without changing other style.
- Security: CSV with `=cmd()` is sanitized; bandit clean.
- Performance: 1000-row bar chart < 500 ms render.

## Dependencies

- `vl-convert-python` (Rust, no Node) — Vega-Lite renderer
- `pandas` (P1) for data manipulation; not needed for inline P0
- `dateutil` for temporal parsing
- `geopandas` (P2 only) for choropleth
