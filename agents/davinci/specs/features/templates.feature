Feature: Templates and brand kits
  Bundled + tenant-authored templates with placeholders and parametric
  prompts; brand kits applied across documents; auto-extract brand kit
  from logo or URL.

  See ../11-templates.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"

  @p0 @critical
  Scenario: Bundled templates are listed by category and doc kind
    When I template_list with category=picture_book
    Then 8 bundled templates are returned
    And each has thumbnail, doc_kind, trust_tier T0

  @p0 @critical
  Scenario: Apply bundled template creates a Document with expected pages
    Given a bundled template "classic 32pp picture book"
    When I template_apply with required variables filled
    Then a new Document is created of doc_kind picture_book
    And page count matches template
    And template.uses_count incremented

  @p0
  Scenario: Apply template to non-empty doc requires replace_pages=True
    Given an existing Document with content
    When I template_apply without replace_pages
    Then TemplateApplyError is raised

  @p0
  Scenario: Required variable missing fails apply
    Given a template requiring variable "title"
    When I template_apply omitting "title"
    Then TemplateApplyError is raised
    And no Document is mutated

  @p0
  Scenario: Variable type mismatch raises
    Given a template variable "age" of type INT
    When I template_apply with age="five"
    Then TemplateApplyError is raised (uncoerceable)

  @p0
  Scenario: Parametric layer regenerates with prompt template
    Given a template with a PARAMETRIC layer prompt "{{character}} riding a {{vehicle}}"
    When I template_apply with character="Lily", vehicle="dragon"
    Then a generation request is made with prompt "Lily riding a dragon"

  @p0
  Scenario: Brand kit creation with palette + fonts + logos
    When I brand_kit_create with name "Acme", palette of 5 colors,
      fonts (display + body + mono), logos (primary + monochrome), voice_prompt "playful"
    Then a BrandKit exists in tenant scope
    And it has 5 palette entries, 3 fonts, 2 logos

  @p0
  Scenario: Brand kit apply remaps brand colours and fonts on document
    Given a Document with text layers using a generic palette
    And a BrandKit with a defined palette + body font
    When I brand_kit_apply
    Then text layers using brand-mapped colours are remapped to the kit
    And text layers using the body slot use the kit's body font

  @p0
  Scenario: Brand kit apply is idempotent
    Given a Document with a BrandKit applied
    When I brand_kit_apply the same kit again
    Then no further changes occur

  @p0
  Scenario: Auto-extract brand kit from logo upload
    Given an uploaded logo blob
    When I brand_kit_extract_from_logo
    Then a BrandKit is produced with palette extracted from the image
    And bundled fonts are used as defaults
    And the logo is added as PRIMARY variant

  @p0 @security
  Scenario: Auto-extract brand kit from URL passes through Warden
    Given a target URL
    When I brand_kit_extract_from_url
    Then the fetched HTML and screenshot are scanned by Warden
    And a flagged response prevents kit creation

  @p0 @security
  Scenario: Cross-tenant template access denied
    Given a tenant-scoped Template owned by tenant "globex"
    When alice (tenant "acme") tries template_get
    Then TemplateNotFoundError is raised

  @p0 @security
  Scenario: Community template T4 cannot be applied without trust escalation
    Given a community-provenance template at trust tier T4
    When alice attempts template_apply
    Then TemplateTrustViolationError is raised

  @p0
  Scenario: Built-in template applied is version-pinned in the document
    Given a built-in template at template_version 3
    When applied
    Then the new Document records template_id and template_version=3

  @p0
  Scenario: BrandKit palette colourblind-safe check WARN if pair fails
    Given a BrandKit with two indistinguishable swatches under deutan simulation
    When I palette_colorblind_check
    Then a WARN result is returned
