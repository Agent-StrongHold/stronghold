Feature: Smart resize
  Re-layout a Page to a different aspect ratio while preserving subject
  framing, text hierarchy, and brand consistency.

  See ../14-smart-resize.md.

  Background:
    Given an authenticated user in tenant "acme"
    And a Page of size 2400x2400 (square) with subject + text + logo

  @p0 @critical
  Scenario: Smart resize square → portrait keeps subject centred
    When I smart_resize to 1080x1920 (9:16) with strategy=SMART_AUTO
    Then a new Page with target dims exists
    And the subject layer is centred within its target bbox
    And the logo is pinned to a corner

  @p0
  Scenario: Aspect mild change uses outpaint
    When I smart_resize from 2400x2400 to 2400x2700 (mild 1:1 → 8:9)
    Then the bg layer is outpainted (not regenerated)

  @p0
  Scenario: Aspect dramatic change regenerates bg
    When I smart_resize from 2400x2400 to 1080x1920 (dramatic 1:1 → 9:16)
    Then the bg layer is regenerated with the same prompt + new dims
    And the original prompt and style lock are preserved

  @p0
  Scenario: Text re-flow shrinks within bounds
    Given a text layer at 24pt that doesn't fit at the new target
    When smart_resize runs
    Then the text shrinks by up to 20% (within accessibility floor)
    Or alternate alignment is used

  @p0
  Scenario: Text shrink > 30% aborts with helpful error
    Given a text layer that requires 35% shrink at the target
    When smart_resize runs
    Then SmartResizeTextOverflowError is raised
    And the error suggests: shorten copy, smaller layer, or crop

  @p0
  Scenario: Logo preserved at corner with min size
    Given a logo currently at corner with size 80x40
    When smart_resize to a smaller target requires shrinking
    Then the logo scales down to ≥ 24px min
    And remains pinned to its original corner

  @p0 @critical
  Scenario: Smart resize on identical dims is idempotent (no-op)
    Given a Page of 2400x2400
    When smart_resize to 2400x2400
    Then the resulting Page byte-equals the input

  @p0
  Scenario: STRETCH on > 20% diff warns explicitly
    When I smart_resize with strategy=STRETCH and aspect diff 30%
    Then the operation warns "stretch may distort"
    And proceeds

  @p0
  Scenario: Multi-target batch processes targets in parallel
    Given a Page and 6 targets in social_kit
    When smart_resize_batch is invoked
    Then 6 new Pages are produced
    And similar-aspect targets share a regenerated bg cache

  @p0
  Scenario: Brand kit palette preserved during bg regeneration
    Given a Page with brand_kit
    When smart_resize triggers a bg regen
    Then the regen prompt includes brand_kit palette terms

  @p0
  Scenario: Multiple subjects: warn if target too narrow for all
    Given a Page with 3 subjects
    When smart_resize to a very narrow target
    Then a warning lists subjects that may be cropped or overlap

  @p1 @perf
  Scenario: Full social_kit on a single page within budget
    Given a Page and a 6-target social_kit
    When smart_resize_batch runs with shared bg regens
    Then all 6 pages are produced in under 30 seconds
