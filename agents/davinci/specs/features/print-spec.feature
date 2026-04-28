Feature: Print specification
  Per-Page declaration of trim/bleed/safe-area/DPI/colour mode driving
  generative quality, layout constraints, and export pipeline.

  See ../08-print-spec.md.

  Background:
    Given an authenticated user in tenant "acme"

  @p0 @critical
  Scenario Outline: Standard sizes resolve to expected pixel dims at 300 DPI
    When I create a Page with print_spec_named "<name>" at dpi 300
    Then the trim_size is <pixels>

    Examples:
      | name                   | pixels       |
      | us_letter              | (2550, 3300) |
      | a4                     | (2480, 3508) |
      | a3                     | (3508, 4961) |
      | a2                     | (4961, 7016) |
      | tabloid                | (3300, 5100) |
      | picture_book_square    | (2400, 2400) |
      | picture_book_portrait  | (2550, 3300) |
      | board_book             | (1800, 1800) |
      | movie_poster           | (7200, 10800)|

  @p0 @critical
  Scenario: Bleed canvas extends trim by bleed pixels each side
    When I create a Page with trim 2400x2400 and bleed 38
    Then the bleed canvas is 2476x2476

  @p0
  Scenario: Safe area is centred inside trim by safe_area px each side
    When I create a Page with trim 2400x2400, safe_area 75
    Then the safe rect is (75, 75, 2325, 2325)

  @p0 @critical
  Scenario: Generative request below print DPI raises DPILowError
    Given a Page with dpi 300 and trim 2400x2400
    And a layer rendered at 1200x1200 destined for print
    When I attempt to use the layer at full page coverage
    Then DPILowError is raised
    And the suggested action is to upscale or regenerate at higher dims

  @p0
  Scenario: CMYK conversion at export uses embedded ICC
    Given a Page with color_mode CMYK and icc_profile "ISO_Coated_v2_300_eci"
    When I export to PDF
    Then the PDF embeds the ISO_Coated_v2_300_eci profile
    And rendered colours are converted from sRGB to CMYK

  @p0
  Scenario: Pure black text uses rich-black recipe in CMYK
    Given a CMYK page with #000000 text
    When the page is rendered for export
    Then the text uses C0 M0 Y0 K100 (not converted CMYK)

  @p0
  Scenario: Bleed missing on background triggers preflight failure
    Given a Page with bleed 38 and a bg layer covering only the trim rect
    When I run preflight
    Then bg_covers_bleed FAILS

  @p0
  Scenario: Picture book with odd page count warns
    Given a picture_book document with 33 pages
    When I run preflight
    Then page_count_parity WARNs

  @p0 @security
  Scenario: PDF export does not embed PII unless opted in
    Given a Document with owner_id "alice"
    When I export to PDF without embed_metadata_pii
    Then the PDF Author and Producer fields contain neither "alice" nor email

  @p0
  Scenario: Saddle-stitch with too many pages warns
    Given a document with binding=SADDLE_STITCH and 96 pages
    When I run preflight
    Then binding_creep_safe WARNs

  @p0
  Scenario: Custom trim with non-finite numbers rejected
    When I create a Page with trim_size (NaN, 1000)
    Then InvalidPageSizeError is raised

  @p1
  Scenario: Mixed-DPI layers warn when below page DPI
    Given a Page with dpi 300
    And a raster layer with native dpi 150
    When I run preflight
    Then dpi_minimum WARNs for that layer
