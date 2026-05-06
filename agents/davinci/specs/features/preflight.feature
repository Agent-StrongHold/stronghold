Feature: Pre-flight validation
  Structured lint over a Document; gates export; produces a report keyed
  to specific layers/pages with optional fix suggestions.

  See ../22-preflight.md.

  Background:
    Given an authenticated user in tenant "acme"

  @p0 @critical
  Scenario: Preflight on a clean fixture returns OK
    Given a fixture Document "clean_fixture"
    When I run preflight
    Then the report level is OK
    And summary.failures == 0
    And summary.warnings == 0

  @p0 @critical
  Scenario: Preflight detects text crossing safe area
    Given a Page with a text layer overlapping the safe-area rect
    When I run preflight
    Then text_in_safe_area FAILS for that layer
    And the fix_suggestion has action "transform_layer" with corrected position

  @p0
  Scenario: Preflight detects missing background bleed
    Given a Page where the background layer does not cover bleed
    When I run preflight
    Then bg_covers_bleed FAILS

  @p0
  Scenario: Preflight detects raster below print DPI
    Given a Page at 300 DPI with a 800x800 raster covering full trim
    When I run preflight
    Then dpi_minimum FAILS for the raster layer

  @p0
  Scenario: Preflight detects non-embeddable font
    Given a layer using a font with embedding rights restricted to "preview"
    When I run preflight
    Then fonts_embeddable FAILS

  @p0 @critical
  Scenario: Preflight blocks export by default on FAIL
    Given a Document with at least one preflight FAIL
    When I attempt to export to PDF
    Then PreflightFailedError is raised
    And the error wraps the report

  @p0
  Scenario: Preflight allows export with ignore_preflight=True
    Given a Document with at least one preflight FAIL
    When I export to PDF with ignore_preflight=True
    Then export succeeds
    And the WARN/FAIL findings are logged in the audit entry

  @p0
  Scenario: Auto-fix resolves a known fixable failure
    Given a preflight report with a text_in_safe_area FAIL with fix_suggestion
    When I apply preflight_fix on the FAIL
    Then re-running preflight reports OK on that rule
    And the layer's transform matches the suggested correction

  @p0
  Scenario: Silenced rule does not surface in subsequent reports
    Given a preflight WARN for orphan_widow on layer L1
    When I silence the rule for L1
    And re-run preflight
    Then orphan_widow does not appear in findings for L1

  @p0
  Scenario: Silence resurfaces if scope underlying changes
    Given a silenced orphan_widow on L1
    When L1's text content changes
    And I re-run preflight
    Then orphan_widow may resurface for L1

  @p0
  Scenario: Spell check uses document language and locale
    Given a Document with language "en-US"
    And a text layer with content "colour"
    When I run preflight
    Then spelling_check WARNs (US locale flags "colour")

  @p0
  Scenario: Reading-level rule matches age band
    Given an early_reader Document with age_band 5_7
    And a text layer with FK grade 6.0
    When I run preflight
    Then reading_level_match WARNs (1+ grade above target)

  @p0 @security
  Scenario: Tenant-isolation rule cannot be silenced
    When I attempt to silence the tenant_assets_only rule
    Then the action is rejected

  @p0
  Scenario: Style-lock drift score over threshold WARNs
    Given a Document with style_lock with drift_threshold 0.25
    And a layer whose vision-LLM drift score is 0.4
    When I run preflight
    Then style_lock_drift WARNs for that layer

  @p0
  Scenario: Untimed caption FAILS for video document
    Given a video Document with a caption layer lacking word_timings
    When I run preflight
    Then untimed_caption FAILS

  @p0
  Scenario: Massive report paginates and groups duplicates
    Given a Document with 1000 pages each with the same WARN
    When I run preflight
    Then findings are paginated (max 200 per scope)
    And duplicates are grouped under a representative

  @p1
  Scenario: Race condition: stale fix attempt fails loudly
    Given a preflight report at version 5
    And the layer mutated to version 6
    When I attempt preflight_fix referring to version 5 expectation
    Then the fix is rejected with stale-version error
