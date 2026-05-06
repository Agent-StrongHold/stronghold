Feature: Critics orchestration
  Per-concern critics (Type, Color, Composition, Prompt, Prop, Accessibility,
  Cost) consume Corrections, refine domain-specific learnings, and inject
  directives at prompt-build time.

  See ../30-critics.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"

  @p0 @critical
  Scenario: Each critic subscribes only to its watched correction kinds
    When the critic registry initializes
    Then Type Critic watches [TEXT_EDIT, FONT_CHANGE, ...]
    And Color Critic watches [COLOR_CHANGE]
    And Composition Critic watches [TRANSFORM_*, REORDER, LAYOUT_APPLY]
    And Prompt Critic watches [REGEN_WITH_NEW_PROMPT]
    And Prop Critic watches [REPLACE_PROP, REPLACE_CHARACTER, asset-scoped TRANSFORM_*]
    And Accessibility Critic watches [FONT_CHANGE flagged, COLOR_CHANGE flagged, ALT_TEXT_EDIT]

  @p0
  Scenario: Type Critic promotes PREFER_FONT_FAMILY from 4 swaps
    Given alice has 4 FONT_CHANGE corrections to "Atkinson Hyperlegible"
    When critic_run for Type
    Then a PREFER_FONT_FAMILY learning exists at scope USER
    And the critic_id is "TYPE"

  @p0
  Scenario: Color Critic promotes REQUIRES_BRAND_KIT_USE on repeated brand swaps
    Given 3 corrections each swap to a brand-kit color
    When critic_run for Color
    Then a REQUIRES_BRAND_KIT_USE learning exists at DOCUMENT scope

  @p0
  Scenario: Accessibility Critic min_floor 0.5 prevents full decay
    Given a REQUIRES_ACCESSIBILITY_FONT learning unreinforced for years
    When decay runs
    Then weight is at least 0.5

  @p0 @critical
  Scenario: Application precedence at prompt build (Accessibility > Color > Type > ...)
    Given conflicting learnings from Accessibility, Color, Type
    When prompt build queries learnings
    Then the directive from Accessibility is applied first
    And lower-precedence directives are downgraded

  @p0
  Scenario: User opt-out of a critic disables its learning
    Given alice critic_enable Cost=false
    When new Cost-related corrections accumulate
    Then no Cost learnings are promoted

  @p0
  Scenario: Cost critic disabled by default (privacy)
    When the critic registry initializes for a new user
    Then Cost critic enabled=false

  @p0 @security
  Scenario: Cross-tenant critic outputs never shared
    Given alice (acme) and bob (globex) both have similar Corrections
    When critics run
    Then alice's learnings reference only her Corrections
    And bob's are unaffected

  @p0
  Scenario: Surface event for newly promoted learning includes critic name
    Given a Type Critic just promoted PREFER_FONT_FAMILY
    Then a UI surface event exists referencing critic="TYPE"
    And it offers "apply across this book" / "just here" / "don't ask again"

  @p0
  Scenario: Critic explanation on a learning
    Given a promoted learning
    When critic_explain is invoked
    Then a human-readable string explains the supporting Corrections + heuristics

  @p0
  Scenario: New critic added back-fills against history within window
    Given a new critic added to the registry
    When critic_run for the new critic
    Then it processes Corrections within the configured back-fill window
    And learnings tagged "new_critic_backfill"

  @p1
  Scenario: Critic that observes nothing eventually flags "no signal" to admin
    Given a critic with min_floor != 0 and no relevant Corrections for N days
    When monitoring runs
    Then a "no signal" warning surfaces to tenant admin
