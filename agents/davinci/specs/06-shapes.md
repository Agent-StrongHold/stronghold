# 06 — Shapes & Vector Primitives

**Status**: P0. Infographics are 70% shapes + connectors + text.
**One-liner**: shape layers store vector geometry; rendered to bitmap on
demand at any scale; no node-edit UI.

## Problem it solves

Today the canvas is raster-only. Infographics need clean arrows, callouts,
banners, charts (delegated to §12), connectors between elements, and decorative
shapes that survive zoom and resize. Speech bubbles for children's books,
ribbons + badges for posters, flowchart arrows for infographics — all need
vector primitives that scale cleanly to print DPI.

## Data model

```
ShapeSource (frozen):
  kind: ShapeKind
  geometry: ShapeGeometry           # tagged union per kind
  fill: Fill                        # solid | gradient | pattern | none
  stroke: Stroke                    # color, width, dash, cap, join, position
  corner_radius: int = 0            # for rect-like kinds

ShapeKind (enum):
  RECTANGLE
  ELLIPSE
  LINE
  POLYLINE
  POLYGON
  PATH                              # arbitrary cubic Bézier
  ARROW
  STAR
  SPEECH_BUBBLE
  CALLOUT
  RIBBON
  BANNER

Fill (tagged union):
  SolidFill:    {kind: "solid", color: Color, opacity: float}
  GradientFill: {kind: "gradient", stops: tuple[GradientStop, ...], type: linear|radial, angle: float}
  PatternFill:  {kind: "pattern", image_blob_id: str, scale: float, repeat: tile|mirror|stretch}
  NoneFill:     {kind: "none"}

Stroke (frozen):
  color: Color
  width: float = 1.0
  dash_pattern: tuple[float, ...] = ()
  cap: LineCap = BUTT               # BUTT | ROUND | SQUARE
  join: LineJoin = MITER            # MITER | ROUND | BEVEL
  position: StrokePosition = CENTER # INSIDE | CENTER | OUTSIDE
```

### ShapeGeometry per kind

```
RectangleGeometry:    {width, height}
EllipseGeometry:      {width, height}
LineGeometry:         {x1, y1, x2, y2}
PolylineGeometry:     {points: tuple[(x,y), ...]}
PolygonGeometry:      {points: tuple[(x,y), ...], closed: bool = True}
PathGeometry:         {commands: tuple[PathCommand, ...]}  # SVG-ish: M, L, C, Q, Z
ArrowGeometry:        {x1, y1, x2, y2, head_size: int, head_style: triangle|chevron|circle}
StarGeometry:         {points: int >= 3, inner_radius, outer_radius}
SpeechBubbleGeometry: {width, height, tail_x, tail_y, tail_width, corner_radius}
CalloutGeometry:      {anchor_x, anchor_y, body_x, body_y, body_w, body_h, style: rect|rounded|cloud}
RibbonGeometry:       {width, height, fold_depth, taper_ratio}
BannerGeometry:       {width, height, curvature}
```

## API surface (canvas tool actions)

| Action | Args | Effect |
|---|---|---|
| `shape` | `kind, geometry, fill, stroke, position, [page_id]` | new shape layer |
| `shape_update` | `layer_id, geometry?, fill?, stroke?` | replace fields |
| `path_op` | `op: union\|subtract\|intersect\|exclude, layer_ids: tuple[str, ...]` | new shape layer |
| `connector` | `from_layer_id, to_layer_id, style: line\|arrow\|orthogonal, [stroke]` | new shape with auto-routing |
| `connector_anchor` | `connector_id, end: from\|to, anchor: top\|bottom\|left\|right\|center\|nearest` | re-anchor |
| `align_to_path` | `layer_id, path_layer_id, t: float in [0,1]` | place a layer on a path |

## Connector routing

Two algorithms:

- `line` / `arrow` — straight line from anchor on source to anchor on target,
  arrowhead optional.
- `orthogonal` — Manhattan routing with auto-bend; uses A* on a coarse grid
  derived from page layout to avoid intersecting other layers' bboxes.

Connectors are live: when the source or target moves, the connector
auto-recomputes on the next render. The connector stores `(from_layer_id,
from_anchor, to_layer_id, to_anchor, style)`, not absolute coordinates.

## Boolean path ops

`path_op` operates on PATH or any kind that can be flattened to a path
(everything except `LINE`, `ARROW`). Backend: `pyclipper` for integer-precision
ops, with input/output via Path geometry. Result is always a `PATH` layer.

## Edge cases

1. **Self-intersecting polygon** — passed through `make_valid` (Shapely);
   warn; reject if result area is 0.
2. **Stroke wider than shape** — clipped to shape's expanded bbox.
3. **Connector to a deleted layer** — invalid state; render shows a red
   dashed placeholder; agent must `connector_update` or remove.
4. **Connector causing visual cycle** (A→B, B→A overlapping) — both
   routed; agent rule: prefer orthogonal with offset.
5. **Pattern fill at scale > image size** — tile + repeat per setting;
   warn at >10× tile count.
6. **Star with `points < 3`** — `ShapeParamsError`.
7. **Path with non-finite numbers** — reject.
8. **Speech bubble tail outside body bbox** — allowed (it points at
   something); validated only that tail width > 0.
9. **Rasterization at low DPI** — anti-aliasing must match Pillow's default
   to avoid jagged edges; tested against fixtures.
10. **Boolean op produces empty result** — return `NoneFill` empty path
    layer; warn.

## Errors

- `ShapeParamsError(ConfigError)`
- `BooleanOpFailedError(ToolError)`
- `ConnectorAnchorError(ConfigError)`

## Test surface

- Unit: each ShapeKind constructs valid geometry; defaults; coordinate
  validation; gradient stop ordering.
- Rendering: golden PNGs per kind at 1× and 4× DPI to validate vector→raster
  consistency.
- Boolean ops: union(A,A) == A; intersect(A,A) == A; subtract(A,A) == empty;
  associativity for union and intersect.
- Connector: source-move triggers recompute; orthogonal avoids crossing
  registered obstacles.
- Property (hypothesis): for any geometry serialized + deserialized, the
  rendered bytes match exactly.

## Dependencies

- Pillow (existing) for rasterization
- `pyclipper` (new) for boolean ops
- `shapely` (already added in §03) for validation
- `cairo` / `cairosvg` (new, optional) for SVG export of vector layers (§13)
