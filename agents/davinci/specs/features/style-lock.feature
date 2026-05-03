Feature: Style lock
  Per-Document constraint that injects style direction into every generative
  call and validates outputs against the locked style.

  See ../09-style-lock.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a Document "D1"

  @p0 @critical
  Scenario: Create a style lock from a hero illustration
    Given an existing rendered "hero" Layer
    When alice runs style_lock_create_from_image with the hero blob
    Then a StyleLock is created
    And palette has between 3 and 7 colours
    And rendering_style_prompt is non-empty (vision-LLM extracted)
    And reference_palette_extracted is true

  @p0
  Scenario: Create a style lock from manual brief
    When alice runs style_lock_create_from_brief with prompt "watercolour, soft, warm",
    palette of 5 colours, line_weight FINE, lighting NATURAL, mood PLAYFUL
    Then the StyleLock fields match the input
    And reference_image_blob_id is null

  @p0 @critical
  Scenario: Apply a style lock to a Document
    Given a StyleLock and a Document without a lock
    When I style_lock_apply
    Then the Document references the lock id
    And subsequent generate prompts include the rendering_style_prompt suffix

  @p0
  Scenario: Drift score for an aligned generation is low
    Given a StyleLock with reference image
    And a freshly-generated Layer matching the reference style
    When I style_lock_check on the layer
    Then the score is below the lock's drift_threshold

  @p0 @critical
  Scenario: Drift score above threshold is flagged in pre-flight
    Given a StyleLock with drift_threshold 0.25
    And a generated Layer whose drift score is 0.4
    When pre-flight runs
    Then style_lock_drift WARNs for that layer

  @p0
  Scenario: Refining a lock bumps version
    Given a StyleLock at version 3
    When I style_lock_refine adding a colour to palette
    Then a new StyleLock at version 4 exists
    And per-page lock_version on existing pages is unchanged

  @p0
  Scenario: Lock applied retroactively does not auto-regenerate
    Given a Document with several pages, no lock
    When I style_lock_apply
    Then existing pages are NOT regenerated
    And drift scores for existing pages are recorded

  @p0
  Scenario: Lock with no reference image uses textual description only
    Given a StyleLock with no reference_image
    When I style_lock_check on a Layer
    Then the score is computed from textual description
    And metadata records "text_only_mode"

  @p0
  Scenario: Vision-LLM unavailable returns null score, downgrades preflight
    Given the vision-LLM endpoint is down
    When I style_lock_check on a Layer
    Then StyleDriftCheckUnavailableError is raised
    And calling preflight downgrades the rule to INFO

  @p0
  Scenario: LoRA wins over textual injection when set
    Given a StyleLock with lora_id set
    When generation builds a request
    Then the LoRA is included
    And the textual style suffix is omitted (or downgraded)

  @p0
  Scenario: Cross-document lock reuse references the same lock id
    Given two Documents both reference the same StyleLock
    When the lock is refined
    Then the refinement is visible to both Documents
    And a warning is shown to the editor of each affected Document

  @p0 @security
  Scenario: Cross-tenant style_lock_load denied
    Given a StyleLock owned by tenant "globex"
    When alice (tenant "acme") tries style_lock_load by name
    Then StyleLockNotFoundError is raised
