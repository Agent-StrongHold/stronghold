Feature: Template authoring
  Save a Document or Page as a reusable Template with placeholders, locked
  layers, and parametric prompts.

  See ../17-template-authoring.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And alice has a finished Document "D1"

  @p0 @critical
  Scenario: Authoring session starts at SOURCE
    When alice runs template_authoring_start with source_document_id D1
    Then a TemplateAuthoringSession is created
    And current_step is SOURCE

  @p0
  Scenario: Auto-suggest layer markings based on content kind
    Given a session at SLOT_MARKING with a Page containing title text + body text + bg illustration + logo
    Then Da Vinci proposes:
      | layer       | intent       | placeholder         |
      | title       | PLACEHOLDER  | TEXT_TITLE          |
      | body        | PLACEHOLDER  | TEXT_BODY           |
      | background  | PARAMETRIC   | (prompt template)   |
      | logo        | LOCKED       | (n/a)               |

  @p0 @critical
  Scenario: Each PARAMETRIC layer requires a prompt template
    Given a session with one layer marked PARAMETRIC and no prompt_template
    When I template_authoring_publish
    Then TemplateAuthoringValidationError is raised

  @p0
  Scenario: Published template uses TrustTier T3 by default for regular users
    Given alice (regular user, not admin) finishes authoring
    When publish completes
    Then the resulting Template has trust_tier T3
    And provenance USER

  @p0
  Scenario: Admin user publishes at T2
    Given carol (tenant admin) finishes authoring
    When publish completes
    Then the resulting Template has trust_tier T2

  @p0
  Scenario: Variable referenced in prompt but not declared blocks publish
    Given a PARAMETRIC layer with prompt "{{undeclared}} rides {{declared}}"
    And only "declared" exists in variables
    When I template_authoring_publish
    Then TemplateAuthoringValidationError lists "undeclared"

  @p0
  Scenario: Preview renders the template with sample variables
    Given a session with all required variables declared
    When I template_authoring_preview with sample values
    Then a Document instance is rendered (without saving)
    And the preview reflects the substituted variables

  @p0
  Scenario: Authoring session lifecycle steps in order
    Given a session at SOURCE
    When I advance through SCOPE, SLOT_MARKING, VARIABLE, PROMPT_TEMPLATE,
      BRAND_KIT, STYLE_LOCK_SEED, METADATA, PUBLISH
    Then each transition is valid

  @p0
  Scenario: Abandon discards in-progress session after retention
    Given a session in progress
    When I template_authoring_abandon
    And retention sweep runs
    Then the session record is deleted
    And no Template was published

  @p0
  Scenario: Two layers reference the same variable id
    Given two layers both set placeholder variable_id "title"
    When publishing
    Then publish succeeds
    And applying the template fills both layers from a single variable value

  @p0 @security
  Scenario: Cross-tenant publish is rejected
    Given alice's session in tenant "acme"
    When publishing tries to write into tenant "globex"
    Then PermissionDeniedError is raised

  @p0
  Scenario: Renaming a variable bumps template version
    Given a published Template at version 1
    When alice republishes with one variable id renamed
    Then version is 2
    And old instances retain their original bindings (no breakage)
