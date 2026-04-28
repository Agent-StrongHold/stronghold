Feature: Shapes and vector primitives
  Vector geometry rendered to bitmap on demand. Rectangles, ellipses, paths,
  arrows, stars, speech bubbles, banners, callouts; boolean path ops; live
  connectors between layers.

  See ../06-shapes.md.

  Background:
    Given a Page of size 1024x1024

  @p0 @critical
  Scenario Outline: Render basic shapes
    When I create a <kind> shape with valid geometry
    Then the layer renders successfully
    And the rasterized output is non-empty

    Examples:
      | kind          |
      | RECTANGLE     |
      | ELLIPSE       |
      | LINE          |
      | POLYLINE      |
      | POLYGON       |
      | PATH          |
      | ARROW         |
      | STAR          |
      | SPEECH_BUBBLE |
      | CALLOUT       |
      | RIBBON        |
      | BANNER        |

  @p0
  Scenario: Rectangle with corner radius rounds corners
    When I create a RECTANGLE with width=200, height=100, corner_radius=20
    Then the rendered shape has rounded corners of radius 20px

  @p0
  Scenario: Stroke position changes the visual rendering
    Given a RECTANGLE 100x100 with stroke width=10
    When stroke position is INSIDE
    Then the stroke is drawn entirely inside the shape bounds
    When stroke position is OUTSIDE
    Then the shape's outer bounding box is 120x120
    When stroke position is CENTER
    Then the stroke straddles the boundary

  @p0
  Scenario Outline: Fill kinds render correctly
    Given a RECTANGLE 200x200 layer
    When fill is <fill>
    Then the shape renders with the expected fill

    Examples:
      | fill                          |
      | SolidFill(#FF00FF, 1.0)       |
      | GradientFill linear 0..#FFF   |
      | GradientFill radial 0..#000   |
      | PatternFill tile               |
      | NoneFill                       |

  @p0
  Scenario: Star with points < 3 raises
    When I create a STAR with points=2
    Then ShapeParamsError is raised

  @p0
  Scenario: Path with non-finite numbers raises
    When I create a PATH with a NaN coordinate
    Then ShapeParamsError is raised

  @p0
  Scenario: Self-intersecting polygon is corrected by Shapely
    When I create a POLYGON with self-intersecting vertices
    Then the geometry is passed through make_valid
    And a warning is emitted
    And the rendered result is a valid simple polygon

  @p0
  Scenario: Speech bubble tail can point outside the body
    Given a SPEECH_BUBBLE with body 200x100 and tail at (250, 100)
    Then the shape renders with the tail outside the body bounds
    And no error is raised

  @p0 @critical
  Scenario: Boolean union of two overlapping rectangles
    Given two RECTANGLEs A and B that overlap
    When I path_op union [A, B]
    Then the result is a PATH layer
    And the result's area equals area(A) + area(B) - area(A∩B)

  @p0
  Scenario: Boolean intersect of two non-overlapping rectangles is empty
    Given two non-overlapping RECTANGLEs A and B
    When I path_op intersect [A, B]
    Then the result is an empty PATH layer
    And a warning is emitted

  @p0
  Scenario: Boolean union is associative
    Given three shapes A, B, C
    When I compute union(union(A, B), C) and union(A, union(B, C))
    Then the resulting paths are geometrically equivalent

  @p0
  Scenario: Boolean intersect is commutative
    Given two shapes A and B
    When I compute intersect(A, B) and intersect(B, A)
    Then the resulting paths are geometrically equivalent

  @p0
  Scenario: Boolean subtract A-B differs from B-A in general
    Given two overlapping shapes A and B with different areas
    When I compute subtract(A, B) and subtract(B, A)
    Then the resulting paths differ

  @p0
  Scenario: Connector references its endpoints by id
    Given two layers L1 and L2
    When I create a connector from L1 to L2 with style=arrow
    Then the connector's data stores (L1.id, L2.id), not absolute coords

  @p0
  Scenario: Connector recomputes when endpoint moves
    Given a connector from L1 to L2 with style=line
    When I move L2 by (200, 0)
    And re-render the page
    Then the connector's rendered geometry has been recomputed
    And the new geometry's endpoint matches L2's new anchor

  @p0
  Scenario: Connector to deleted layer renders a placeholder
    Given a connector from L1 to L2
    When L2 is deleted
    Then rendering shows a red dashed placeholder
    And the agent rule is to update or remove the connector

  @p0
  Scenario: Orthogonal connector avoids registered obstacles
    Given a connector with style=orthogonal from L1 to L2
    And an obstacle layer between them
    When the connector is routed
    Then the routed path bends around the obstacle's bbox

  @p0 @perf
  Scenario: Vector renders consistently across DPI
    Given a STAR shape
    When I render at 1x DPI and at 4x DPI
    Then the 4x output is geometrically the 1x output upscaled
    And anti-aliasing matches Pillow's default

  @p1
  Scenario: Boolean op producing empty path returns NoneFill empty layer
    Given two identical shapes A and A
    When I path_op subtract [A, A]
    Then an empty PATH layer is returned
    And a warning is emitted

  @p1
  Scenario: Pattern fill at scale > image size warns
    Given a 32x32 pattern image
    And a RECTANGLE 1024x1024 with PatternFill scale=1.0 repeat=tile
    When I render
    Then the warning "high_tile_count" is emitted
    And the shape still renders correctly
