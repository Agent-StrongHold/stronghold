Feature: Export
  Document → bytes in PNG/JPG/WebP/PDF/SVG/ePub/PPTX. Pre-flight gate;
  embedded metadata; print specs honoured; audit logged.

  See ../13-export.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"

  @p0 @critical
  Scenario: PNG export of a single-page document returns valid PNG
    Given a Document with one Page and one raster Layer
    When I export to PNG
    Then the result is valid PNG
    And dimensions match the Page's print_spec.trim_size
    And alpha channel is preserved

  @p0
  Scenario: Multi-page PNG export defaults to ZIP
    Given a 4-page Document
    When I export to PNG without explicit zip option
    Then the result is a ZIP archive containing 4 PNG files
    And filenames include page ordering

  @p0 @critical
  Scenario: JPG quality option respected
    Given a Document
    When I export JPG with quality=75
    Then the result is a JPG with quality 75 (within Pillow's encoder)

  @p0 @critical
  Scenario: PDF embeds fonts as subsets
    Given a Document with a text layer
    When I export to PDF
    Then fonts are embedded as subsets (not full)
    And the font is re-usable by PDF readers

  @p0
  Scenario: PDF rejects export when a font is non-embeddable
    Given a text layer using a font with embedding rights "preview only"
    When I export to PDF
    Then FontNotEmbeddableError is raised

  @p0 @critical
  Scenario: PDF crop box equals trim, media box equals bleed
    Given a Page with trim 2400x2400 and bleed 38
    When I export to PDF
    Then the PDF crop box is 2400x2400
    And the media box is 2476x2476

  @p0
  Scenario: PDF embeds ICC for CMYK pages
    Given a Page with color_mode CMYK + icc_profile "ISOcoated_v2"
    When I export to PDF
    Then the ICC profile is embedded
    And rendered colours are CMYK-converted

  @p0 @critical
  Scenario: SVG export of a vector-friendly page emits clean SVG
    Given a Page composed only of shapes + text + a single linked raster
    When I export to SVG
    Then the SVG passes XSD validation
    And the raster is referenced via <image> (not data URI by default)

  @p0
  Scenario: SVG export of mostly-raster page emits image-wrapped SVG with warning
    Given a Page composed mostly of raster
    When I export to SVG
    Then the raster is wrapped in <image>
    And a warning is recorded

  @p0 @critical
  Scenario: Pre-flight failure blocks export by default
    Given a Document with at least one preflight FAIL
    When I export
    Then PreflightFailedError is raised
    And the report is attached

  @p0
  Scenario: Pre-flight bypass with ignore_preflight=True
    Given a Document with preflight FAIL
    When I export with ignore_preflight=True
    Then the export proceeds
    And the audit entry records the bypass

  @p0 @security
  Scenario: PDF metadata excludes PII unless opt-in
    Given a Document
    When I export with embed_metadata_pii=false
    Then PDF Author/Producer fields contain neither user nor tenant id

  @p0
  Scenario: Empty document export raises EmptyDocumentError
    Given a Document with 0 pages
    When I export
    Then EmptyDocumentError is raised

  @p0
  Scenario: Concurrent exports of the same doc both succeed
    Given two simultaneous export calls for the same Document
    When both run
    Then both produce valid output
    And the second is served from cache when input identical

  @p0
  Scenario: Audit entry recorded per export
    When I export to PDF
    Then an audit entry has format=PDF, doc_id, byte_size, sha256, user_id

  @p0
  Scenario: Watermarked draft when not all layers are proof
    Given a Document with a draft-tier layer
    When I export with enforce_proof=true
    Then a "DRAFT" watermark is placed in safe area

  @p1
  Scenario: ePub export validates against epubcheck
    Given a picture book Document
    When I export to ePub
    Then the file passes epubcheck

  @p1
  Scenario: PPTX export creates one slide per page
    Given a 5-page Document
    When I export to PPTX
    Then the file has 5 slides
    And images are embedded

  @p1 @perf
  Scenario: 32-page picture book PDF export within budget
    Given a 32-page picture book Document
    When I export to PDF
    Then the export completes in under 30 seconds
