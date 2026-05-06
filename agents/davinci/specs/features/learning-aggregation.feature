Feature: Learning aggregation
  Promote Corrections (§19) into scoped, decaying Learnings consumed by
  future generation. Contradictions resolve; conflicts surface to user.

  See ../20-learning-aggregation.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a clean LearningStore for alice

  @p0 @critical
  Scenario: 3+ same FONT_CHANGE across docs promotes USER-scope Learning
    Given alice has 3 FONT_CHANGE Corrections in 3 different Documents
      all swapping to "Atkinson Hyperlegible"
    When the aggregator runs
    Then a Learning of kind PREFER_FONT_FAMILY exists at scope USER
    And confidence >= 0.7
    And the Learning links to the 3 supporting Correction ids

  @p0 @critical
  Scenario: 2+ same change in one document promotes DOCUMENT-scope
    Given alice has 2 COLOR_CHANGE Corrections in Document D1
      both to brand-kit color "#1A2B3C"
    When the aggregator runs
    Then a Learning of kind PREFER_PALETTE_COLOR exists at scope DOCUMENT
    And document_id == D1

  @p0
  Scenario: Asset-scoped change promotes ASSET-scope refinement
    Given alice has 3 corrections increasing a character's eye size on the same character_asset
    When the aggregator runs
    Then a Learning of kind CHARACTER_REFINEMENT exists at scope ASSET
    And asset_id matches the character

  @p0 @critical
  Scenario: Brand-kit-color reapplied where agent missed → high-confidence learning
    Given alice has 3 corrections each replacing an off-brand color with a brand-kit value
    When the aggregator runs
    Then a Learning of kind REQUIRES_BRAND_KIT_USE exists with confidence >= 0.9

  @p0
  Scenario: Reverted corrections do NOT contribute to promotion
    Given 5 same-kind Corrections, all reverted within 60s
    When the aggregator runs
    Then no Learning is promoted

  @p0
  Scenario: Inverse changes on different docs → no learning (contextual)
    Given correction A: change blue → red on doc D1
    And correction B: change red → blue on doc D2
    When the aggregator runs
    Then no positive Learning is promoted
    And the conflict is recorded (no rule applied)

  @p0
  Scenario: Decay reduces weight without reinforcement
    Given a Learning created 30 days ago, never reinforced
    When the decay job runs
    Then weight = max(min_floor, weight * (decay_factor ** 30))

  @p0
  Scenario: Reinforcement resets last_reinforced_at and bumps weight
    Given an existing PREFER_FONT_FAMILY Learning at weight 0.6
    When a new supporting Correction arrives
    Then the Learning's last_reinforced_at is updated
    And weight = min(1.0, prior_weight * 1.1)

  @p0
  Scenario: Min floor prevents accessibility learnings from full decay
    Given a REQUIRES_ACCESSIBILITY_FONT Learning, no reinforcement for 365 days
    When decay runs
    Then weight is at least 0.5 (min_floor)

  @p0
  Scenario: Pinned Learnings are immune to decay
    Given a Learning with pinned=true
    When decay runs for years
    Then weight remains 1.0

  @p0 @critical
  Scenario: Contradiction resolution: stronger evidence demotes the older
    Given an existing Learning A (PREFER_FONT_FAMILY=Inter, confidence 0.5)
    And a new Learning B (PREFER_FONT_FAMILY=Roboto, confidence 0.9 from new evidence)
    When B is promoted
    Then A.weight halves
    And A.contradicts contains B.id

  @p0
  Scenario: Contradiction with no clear winner asks the user
    Given two Learnings of equal confidence and weight
    When a third related Correction arrives
    Then a UI surface event "ask_user_for_resolution" is queued

  @p0
  Scenario: Application: Learning's rule_data injects directive at prompt build
    Given a USER-scope Learning PREFER_FONT_FAMILY=Atkinson Hyperlegible
    When alice builds a generation request for body text
    Then the prompt builder includes the directive
    And weight = confidence * weight

  @p0
  Scenario: DOCUMENT-scope Learning supersedes USER-scope at apply
    Given alice has a USER PREFER_PALETTE_COLOR=#FFAA00
    And a DOCUMENT-scope override PREFER_PALETTE_COLOR=#0000FF for D1
    When alice generates within D1
    Then the DOCUMENT-scope rule wins

  @p0 @security
  Scenario: Cross-tenant Learnings never cross-pollinate
    Given alice (acme) has Learnings
    And bob (globex) has Learnings
    When the aggregator runs
    Then alice's Learnings reference only alice's Corrections
    And bob's are unaffected

  @p0
  Scenario: Aggregator is idempotent on same input window
    Given a fixed window of Corrections
    When the aggregator runs twice
    Then the produced Learnings match (no duplicates, same fields)

  @p1
  Scenario: Surfacing a newly-promoted Learning to UI
    Given a PREFER_FONT_FAMILY Learning was just promoted
    Then a UI surface event is recorded suggesting "apply across the book"

  @p1 @perf
  Scenario: Aggregator processes 10k corrections within budget
    Given 10k recent Corrections
    When the aggregator runs
    Then the run completes in under 10 seconds
