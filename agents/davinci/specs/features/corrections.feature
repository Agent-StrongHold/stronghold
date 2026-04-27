Feature: Corrections capture
  Every direct-manipulation edit and chat-driven tweak emits a structured
  Correction event for §20 aggregation and §21 LoRA training.

  See ../19-corrections.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a Document with at least one Layer

  @p0 @critical
  Scenario: Direct-manipulation font change emits FONT_CHANGE correction
    Given a text layer with font Comic Sans
    When alice changes the font to Atkinson Hyperlegible via UI
    Then a Correction is recorded
    And kind == FONT_CHANGE
    And source == DIRECT_MANIP
    And before/after snapshots show the font change

  @p0 @critical
  Scenario: Chat-driven tweak emits CHAT-source correction
    Given alice writes "make all dragons rounder" in chat
    When the agent applies the change to layer L1
    Then a Correction is recorded
    And kind matches the change kind (e.g. REGEN_WITH_NEW_PROMPT)
    And source == CHAT

  @p0
  Scenario: Agent-authored changes are NOT captured as user corrections
    Given the agent regenerates a layer (without user request)
    Then NO user-source Correction is recorded for it

  @p0
  Scenario: Undo within 60s flags prior correction as reverted
    Given a recently-recorded Correction
    When alice undoes within 60s
    Then the prior Correction has reverted=true
    And reverted_at is set

  @p0
  Scenario: Coalescing rapid same-layer same-kind ops within 5s
    Given alice toggles a checkbox 5 times within 5s
    When captures occur
    Then 1 Correction (or fewer) is recorded, not 5

  @p0
  Scenario: Bulk action emits a single aggregate correction
    Given alice applies a brand kit to a 32-page Document changing 200 colours
    When captures occur
    Then 1 aggregate Correction is recorded (not 200)
    And kind is COLOR_CHANGE with metadata indicating bulk

  @p0
  Scenario: Wizard-source corrections are tagged separately
    Given alice is in a WizardSession
    When she makes choices that mutate state
    Then captured Corrections have source tagged WIZARD
    And those are excluded from §20 aggregation by default

  @p0
  Scenario: Inferred intent populated by diff-LLM
    Given a FONT_CHANGE correction
    When inference runs
    Then inferred_intent is non-empty
    And mentions the from-font and to-font specifics

  @p0
  Scenario: Inferred intent caching by before/after hash
    Given two identical Corrections
    When inference runs for both
    Then the second uses cached inferred_intent (same hash)

  @p0 @security
  Scenario: Cross-tenant correction_list returns nothing
    Given bob (tenant "globex") has Corrections
    When alice (tenant "acme") tries correction_list
    Then no rows from globex appear

  @p0
  Scenario: User data export contains all and only this user's Corrections
    Given alice has 50 Corrections
    When alice runs correction_export
    Then 50 Corrections are exported
    And no other user's Corrections are present

  @p0
  Scenario: User data deletion sweeps Corrections
    When alice runs correction_delete
    Then alice's Corrections are removed
    And tenant-mate Corrections are unaffected

  @p0
  Scenario: Snapshot too large stores blob refs not pixels inline
    Given a Layer with 30MB raster source
    When the Correction is captured
    Then Correction.before/after store blob refs
    And no pixel bytes are inlined

  @p0
  Scenario: Initial signal_strength is bounded [0.1, 2.0]
    Given any captured Correction
    Then 0.1 <= signal_strength <= 2.0

  @p0
  Scenario: Source AUTO_FIX captured when user accepts pre-flight fix
    Given a preflight fix_suggestion
    When alice accepts it via UI
    Then a Correction is recorded with source=AUTO_FIX
