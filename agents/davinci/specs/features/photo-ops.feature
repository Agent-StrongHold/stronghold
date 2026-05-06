Feature: Photo ops (P2 minimum subset)
  Adjustments, filters, layer styles, and blend modes implemented as Effect
  entries on a Layer's effect stack. Per-mode formulas and golden tests.

  See ../07-photo-ops.md.

  Background:
    Given a Page with one raster Layer "L1" of size 256x256
    And a fixture image "fixtures/portrait_256.png" loaded into "L1"

  @p0
  Scenario Outline: P2 adjustments change the rendered output predictably
    When I add a <kind> effect with <param>=<value> to "L1"
    And I render "L1"
    Then the output differs from the source within tolerance <tolerance>

    Examples:
      | kind         | param   | value | tolerance |
      | BRIGHTNESS   | value   | 0.3   | 0.05      |
      | CONTRAST     | value   | 0.4   | 0.05      |
      | SATURATION   | value   | -0.5  | 0.05      |
      | HUE_SHIFT    | degrees | 60    | 0.10      |
      | EXPOSURE     | stops   | 1.0   | 0.05      |
      | GAMMA        | value   | 1.5   | 0.05      |

  @p0 @critical
  Scenario: INVERT is its own inverse
    Given "L1" rendered as "S0"
    When I add an INVERT effect, render as "S1"
    And I add another INVERT effect, render as "S2"
    Then S0 and S2 are byte-identical

  @p0
  Scenario: BRIGHTNESS(0) is identity
    Given "L1" rendered as "S0"
    When I add a BRIGHTNESS(0.0) effect
    And I render as "S1"
    Then S0 and S1 are byte-identical

  @p0
  Scenario: GAUSSIAN_BLUR with radius=0 is a no-op
    Given "L1" rendered as "S0"
    When I add a GAUSSIAN_BLUR(0) effect
    And I render as "S1"
    Then S0 and S1 are byte-identical

  @p0
  Scenario: SHARPEN amount=0 is a no-op
    Given "L1" rendered as "S0"
    When I add a SHARPEN(0.0) effect
    And I render as "S1"
    Then S0 and S1 are byte-identical

  @p0
  Scenario: VIGNETTE darkens corners
    When I add a VIGNETTE with strength=0.7
    Then corner pixels of the rendered output are darker than the source corner pixels
    And centre pixel is unchanged within tolerance

  @p0
  Scenario: NOISE_ADD changes pixel values without changing bbox
    When I add a NOISE_ADD with amount=0.1
    Then the rendered output's mean luminance is approximately equal to the source's
    And per-pixel diff stddev is non-zero

  @p0 @critical
  Scenario: DROP_SHADOW renders below the layer with offset and blur
    Given a layer with non-trivial alpha
    When I add a DROP_SHADOW dx=10 dy=10 blur=8 color=#000 opacity=0.6
    Then the rendered output has dark pixels in the offset region
    And the layer's alpha is preserved on top of the shadow

  @p0
  Scenario: DROP_SHADOW with zero offset and zero blur on opaque colour matches stroke
    When I add a DROP_SHADOW with dx=0, dy=0, blur=0, color=#000, opacity=1.0
    Then the warning "shadow_invisible_or_redundant" is emitted

  @p0
  Scenario: STROKE width=0 is a no-op with warning
    When I add a STROKE with width=0
    Then the layer is unchanged
    And a warning is emitted

  @p0
  Scenario Outline: Blend modes match per-channel formulas
    Given two layers "back" filled with colour <Cb> and "front" filled with colour <Cs>
    When "front" has blend_mode=<mode>
    And the layers are composited
    Then the result equals <Cresult>

    Examples:
      | mode       | Cb       | Cs       | Cresult                     |
      | NORMAL     | #FF0000  | #0000FF  | #0000FF (front opaque)      |
      | MULTIPLY   | #FFFFFF  | #808080  | #808080                     |
      | MULTIPLY   | #000000  | #808080  | #000000                     |
      | SCREEN     | #000000  | #808080  | #808080                     |
      | SCREEN     | #FFFFFF  | #808080  | #FFFFFF                     |
      | DARKEN     | #FF0000  | #00FF00  | #000000                     |
      | LIGHTEN    | #FF0000  | #00FF00  | #FFFF00                     |
      | DIFFERENCE | #FF0000  | #FF0000  | #000000                     |

  @p0
  Scenario: Layer opacity reduces blend contribution
    Given a layer "front" with blend NORMAL and opacity=0.5
    And a "back" layer
    When composited
    Then the result equals 0.5*front + 0.5*back per channel

  @p0
  Scenario: Effect chain order matters
    Given "L1" with effects [GAUSSIAN_BLUR(8), SHARPEN(2.0)] rendered as "A"
    When I reorder to [SHARPEN(2.0), GAUSSIAN_BLUR(8)] rendered as "B"
    Then "A" and "B" differ

  @p0
  Scenario Outline: Param schema rejects out-of-range values
    When I add a <kind> effect with <param>=<value>
    Then EffectParamsError is raised

    Examples:
      | kind          | param     | value |
      | BRIGHTNESS    | value     | 5.0   |
      | EXPOSURE      | stops     | 10    |
      | GAMMA         | value     | 0.0   |
      | GAUSSIAN_BLUR | radius_px | -1    |
      | NOISE_ADD     | amount    | 1.5   |
      | VIGNETTE      | strength  | 2.0   |

  @p1 @perf
  Scenario: Full P2 effect on 4096x4096 layer renders within budget
    Given a 4096x4096 layer
    And an effect stack with 6 P2 effects
    When I render
    Then the render completes in under 200 ms
