Feature: Effect stack
  Layers carry an ordered list of non-destructive effects. The render pipeline
  applies them head-to-tail, then mask, then blend, then composite. The stack
  is editable: add, update, remove, toggle, reorder.

  See ../01-effect-stack.md.

  Background:
    Given a Document with one Page and one raster Layer "L1" of size 100x100
    And the Layer has an empty effect stack

  @p0 @critical
  Scenario: Adding an effect appends to the stack
    When I add a BRIGHTNESS effect with value 0.2 to "L1"
    Then "L1" has 1 effect
    And the effect's kind is BRIGHTNESS
    And the effect's params are {value: 0.2}
    And the effect is enabled

  @p0 @critical
  Scenario: Adding multiple effects preserves order
    When I add a BRIGHTNESS effect with value 0.2
    And I add a CONTRAST effect with value 0.3
    And I add a GAUSSIAN_BLUR with radius_px 4
    Then "L1" has 3 effects
    And the effect ordering is BRIGHTNESS, CONTRAST, GAUSSIAN_BLUR

  @p0
  Scenario: Inserting at a position shifts later effects
    Given "L1" has effects [BRIGHTNESS, CONTRAST]
    When I add a GAUSSIAN_BLUR at position 1
    Then the effect ordering is BRIGHTNESS, GAUSSIAN_BLUR, CONTRAST

  @p0
  Scenario: Removing an effect drops it from the stack
    Given "L1" has effects [BRIGHTNESS, CONTRAST, GAUSSIAN_BLUR]
    When I remove the CONTRAST effect
    Then "L1" has 2 effects
    And the effect ordering is BRIGHTNESS, GAUSSIAN_BLUR

  @p0
  Scenario: Toggling an effect sets enabled without removing it
    Given "L1" has a BRIGHTNESS effect
    When I toggle the BRIGHTNESS effect to disabled
    Then "L1" has 1 effect
    And that effect is disabled

  @p0 @critical
  Scenario: Disabled effects are skipped during render
    Given "L1" has a BRIGHTNESS effect with value 0.5 (disabled)
    When I render "L1"
    Then the rendered bytes equal the rasterized source unchanged

  @p0
  Scenario: Reordering effects produces different render output
    Given "L1" has effects [GAUSSIAN_BLUR(4), STROKE(width=2)]
    And I capture the render as "blur_then_stroke"
    When I reorder to [STROKE(width=2), GAUSSIAN_BLUR(4)]
    And I capture the render as "stroke_then_blur"
    Then "blur_then_stroke" differs from "stroke_then_blur"

  @p0 @critical
  Scenario: Empty effect stack renders the source unchanged
    When I render "L1"
    Then the rendered bytes equal the rasterized source unchanged

  @p0
  Scenario: Effects on a group layer apply to the composited output
    Given a group Layer "G1" containing "L1" and "L2"
    And "G1" has a GAUSSIAN_BLUR with radius_px 8
    When I render "G1"
    Then the blur is applied to the composited (L1+L2) output, not L1 and L2 individually

  @p0 @critical
  Scenario Outline: Effect param schema validation rejects out-of-range values
    When I add a <kind> effect with <param> = <value>
    Then the action raises EffectParamsError

    Examples:
      | kind          | param     | value |
      | BRIGHTNESS    | value     | 5.0   |
      | BRIGHTNESS    | value     | -2.0  |
      | GAUSSIAN_BLUR | radius_px | -1    |
      | GAUSSIAN_BLUR | radius_px | 9999  |
      | HUE_SHIFT     | degrees   | 360   |
      | HUE_SHIFT     | degrees   | -181  |
      | EXPOSURE      | stops     | 10    |

  @p0
  Scenario: Unknown effect kind raises EffectKindUnknownError
    When I add an effect with kind "WARP_BUBBLE"
    Then the action raises EffectKindUnknownError

  @p0
  Scenario: Stack overflow at 33rd effect
    Given "L1" has 32 effects
    When I add a 33rd effect
    Then the action raises EffectStackOverflowError

  @p0
  Scenario: Same logical state produces byte-identical render
    Given "L1" has effects [BRIGHTNESS(0.2), CONTRAST(0.3)]
    And I capture the render as "A"
    When I add a SATURATION(0.0) effect
    And I remove the SATURATION effect
    And I capture the render as "B"
    Then "A" and "B" are byte-identical

  @p0
  Scenario: Cache hit on identical input
    Given "L1" has effects [BRIGHTNESS(0.2), GAUSSIAN_BLUR(4)]
    When I render "L1" twice
    Then the second render returns from cache
    And both renders are byte-identical

  @p0
  Scenario: Cache invalidation on effect change
    Given "L1" has a BRIGHTNESS(0.2) effect
    And the layer is rendered once (cache populated)
    When I update BRIGHTNESS value to 0.5
    Then the next render does not return from cache

  @p0
  Scenario: Group source cannot transitively reference itself
    Given a group Layer "G1" containing "L1"
    When I add "G1" as a child of "G1"
    Then the action raises EffectParamsError

  @p1
  Scenario: Effect on 1×1 layer is a trivial no-op render
    Given a Layer of size 1x1
    When I add a GAUSSIAN_BLUR(8) effect
    And I render it
    Then no error is raised
    And the rendered output is 1x1

  @p1 @perf
  Scenario: 16-effect stack on 4096x4096 layer renders within budget
    Given a Layer of size 4096x4096
    And the layer has 16 effects of mixed kinds
    When I render it
    Then the render completes in under 2 seconds
