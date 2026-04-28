Feature: Accessibility
  Defaults that favour readability for kids' content; pre-flight catches
  contrast / font / alt-text issues; dyslexia mode; colour-blind safe
  palettes.

  See ../25-accessibility.md.

  Background:
    Given an authenticated user in tenant "acme"

  @p0 @critical
  Scenario Outline: Body size defaults per age band
    Given a Document of kind <kind> with age_band <age>
    When a body text layer is created without explicit size
    Then size_px defaults to <px>

    Examples:
      | kind         | age | px |
      | picture_book | 3_5 | 24 |
      | picture_book | 5_7 | 18 |
      | early_reader | 7_9 | 14 |

  @p0
  Scenario: Body font defaults to Atkinson Hyperlegible for kids' books
    Given a picture_book Document
    When a body text layer is created without explicit font
    Then font_family is "Atkinson Hyperlegible"

  @p0 @critical
  Scenario: WCAG contrast WARN below AA ratio
    Given text colour and background composite with luminance contrast 3.0
    When I run accessibility_report
    Then wcag_text_contrast WARNs (below AA 4.5:1 for normal text)

  @p0
  Scenario: Large text uses 3:1 threshold instead of 4.5:1
    Given text at 24pt with contrast 3.5
    When I run accessibility_report
    Then wcag_text_contrast is OK (large-text threshold met)

  @p0
  Scenario: Alt-text auto-generated for illustration layer
    Given an illustration layer without alt-text
    When the layer is created
    Then alt_text_generate runs
    And the layer has non-empty alt
    And alt does not begin with "an image of"

  @p0
  Scenario: Alt-text edited by user persists
    Given an illustration layer with auto-generated alt
    When alice sets a different alt via alt_text_set
    Then the user-supplied alt is saved
    And it is preserved across re-renders of the layer

  @p0
  Scenario: Colour-blind palette WARN for indistinguishable pair
    Given a brand-kit palette with two colours indistinguishable under deutan simulation
    When I palette_colorblind_check
    Then the result WARNs with the offending pair

  @p0
  Scenario: Reading-level WARN when grade exceeds age band
    Given a Document with age_band 5_7 and body FK grade 5.0
    When I run accessibility_report
    Then reading_level_match WARNs (grade > 3)

  @p0
  Scenario: Reading-level skipped for non-prose pages (cover)
    Given a Document with a cover page containing only title text
    When I run accessibility_report
    Then reading_level_match is not_applicable for that page

  @p0 @critical
  Scenario: Dyslexia mode flips fonts and spacing globally
    Given a Document
    When I dyslexia_mode_toggle on
    Then body font becomes Atkinson Hyperlegible
    And letter_spacing increases by 0.05em on all body text
    And line_height >= 1.6
    And background defaults to #FFF8E7
    And italic body text is disabled

  @p0
  Scenario: Justified alignment surfaces inline accessibility warning
    Given a body text layer with alignment JUSTIFY
    When I render the page
    Then an inline warning shows "justified text reduces readability"

  @p0 @security
  Scenario: Strict accessibility export raises if alt-text missing
    Given a Document with at least one illustration without alt-text
    And export options strict_accessibility=true
    When I export
    Then AltTextRequiredError is raised

  @p0
  Scenario: Document language declaration embedded in PDF
    Given a Document with language "es-MX"
    When I export to PDF
    Then the PDF /Lang catalog attribute is "es-MX"

  @p1
  Scenario: PDF/UA tagged structure with reading order
    Given a Document
    When I export with pdf_subtype=PDFUA
    Then the PDF has /StructTreeRoot
    And reading order matches visual order
    And /Alt attributes are present per illustration

  @p1
  Scenario: Per-page sliding-window contrast catches dark text on busy bg
    Given a text layer over a varying background
    When I run accessibility_report
    Then minimum local contrast (sliding window) is checked
    And a WARN surfaces if any local region drops below threshold
