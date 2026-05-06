Feature: Localization
  Same Document → N languages with auto-translation, script-aware
  typography, re-flow per language metrics, illustration consistency.

  See ../26-localization.md.

  Background:
    Given an authenticated user in tenant "acme"
    And a Document "D1" in language "en-US"

  @p0 @critical
  Scenario Outline: Localize to target language creates linked Document
    When I localization_create source_document_id=D1 target_languages=[<lang>]
    Then a DocumentLocalization exists with target_language=<lang>, status=DRAFT
    And a target Document is created
    And every text layer is translated by an LLM call

    Examples:
      | lang  |
      | es    |
      | fr    |
      | de    |
      | ja    |
      | zh-Hans |
      | ar-SA |

  @p0
  Scenario Outline: Re-flow shrink within accessibility floor for expansion languages
    Given a target language <lang>
    When localization re-flows a text layer
    Then the font may shrink up to 15%
    And the resulting size is at least the accessibility minimum

    Examples:
      | lang |
      | de   |
      | es   |
      | fr   |

  @p0
  Scenario: RTL flips text direction and master page binding side
    Given target_language=ar-SA
    When localization runs
    Then text layers have direction=RTL
    And verso/recto binding sides are swapped on master pages

  @p0
  Scenario: Bidi handles mixed RTL+LTR runs
    Given target text "Visit مرحبا today"
    When rendered
    Then LTR and RTL runs are correctly ordered
    And the brand-name latin run is bidi-isolated

  @p0
  Scenario: Script-appropriate fallback font selected per language
    Given target_language=ja
    When a text layer is re-typed
    Then the font fallback chain includes Noto Sans CJK JP
    And missing-glyph rule does NOT trigger for kana / kanji

  @p0
  Scenario: Illustrations are NOT translated
    Given a Document with character illustrations
    When localized to es
    Then the illustration layers are unchanged in source bytes
    And the same character refs / style lock apply

  @p0
  Scenario: Text baked into illustration triggers user-decision flow
    Given an illustration containing rendered text "Open"
    When localizing to es
    Then a flag surfaces "text baked into illustration: review for translation"
    And nothing is auto-translated in the image

  @p0
  Scenario: LocalizationOverflowError when text won't fit anywhere
    Given a text bbox tight enough that even hyphenation fails
    When localization runs
    Then LocalizationOverflowError is raised for that layer

  @p0
  Scenario: Re-paginate localized Document is idempotent
    Given a localized DocumentLocalization
    When I localization_repaginate
    Then the result equals prior pagination (no spurious changes)

  @p0
  Scenario: Translation refusal surfaces to user manual entry
    Given an LLM that refuses a particular passage
    When translation runs
    Then TranslationFailedError surfaces for the layer
    And the user can supply a manual translation

  @p0 @security
  Scenario: Cross-tenant localization not allowed
    Given source Document owned by tenant "globex"
    When alice (acme) tries localization_create on it
    Then PermissionDeniedError is raised

  @p0
  Scenario: Localized DocumentLocalization status transitions DRAFT→REVIEWED→PUBLISHED
    Given a DRAFT DocumentLocalization
    When alice localization_review accepted=true
    Then status becomes REVIEWED
    When alice publishes
    Then status becomes PUBLISHED

  @p1
  Scenario: Date/number formatting respects locale
    Given a text layer with date "2024-01-15" in en-US
    When localized to de
    Then the rendered date uses German format "15.01.2024"

  @p1
  Scenario: Per-language brand kit overrides source kit
    Given a BrandKit with localized_variants for ja
    When localized to ja
    Then the ja-localized kit applies (display font swapped, etc.)
