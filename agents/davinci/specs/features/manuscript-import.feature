Feature: Manuscript import
  Ingest Word/PDF/Markdown/EPUB manuscripts; auto-paginate per age band;
  mark scene breaks for spot illustrations.

  See ../33-manuscript-import.md.

  Background:
    Given an authenticated user in tenant "acme"

  @p0 @critical
  Scenario Outline: Each format imports without parser errors
    Given a fixture file in <format>
    When I manuscript_import doc_kind=early_reader, age_band=7_9
    Then a Document is created
    And total page count > 0
    And no ManuscriptParseError is raised

    Examples:
      | format    |
      | markdown  |
      | text      |
      | docx      |

  @p0 @critical
  Scenario: Pagination per age band uses the right wpp target
    Given a 6000-word manuscript and age_band 5_7 (60 wpp)
    When I manuscript_import
    Then page count is approximately 100 (within ±10)
    And no page breaks mid-sentence

  @p0
  Scenario: CHAPTER_BREAK forces a new page (TEXT_ONLY chapter-start)
    Given a manuscript with chapter break markers
    When I manuscript_import
    Then each break begins a new TEXT_ONLY chapter-start page

  @p0
  Scenario: Scene-break markers add illustration slots without auto-generation
    Given a manuscript with scene-break markers
    When I manuscript_import
    Then pages with scene breaks gain an illustration PLACEHOLDER layer
    And no generation cost is incurred at import (cost-gated later)

  @p0
  Scenario: DOCX heading styles map to chapters/sections
    Given a DOCX with Heading 1 = chapter, Heading 2 = section
    When I manuscript_import
    Then chapters force new pages
    And section headings render as sub-headings within the same page when possible

  @p0
  Scenario: Markdown headings detected at #/##/###
    Given a Markdown manuscript with # / ## / ### levels
    When I manuscript_import
    Then # → chapter, ## → section, ### → subsection (mapped accordingly)

  @p0
  Scenario: Repaginate respects unchanged input idempotently
    Given a Document imported from manuscript M at age_band 7_9
    When I manuscript_repaginate with the same age_band
    Then the result equals the original

  @p0
  Scenario: Encoding errors detected via chardet, warn at low confidence
    Given a file with mojibake / unknown encoding
    When I manuscript_import
    Then the encoding is auto-detected
    And if confidence is low a warning is emitted

  @p0 @security
  Scenario: ZIP-bomb-shaped DOCX rejected with size limit
    Given a malicious DOCX with a tiny outer size + huge inner expansion
    When I manuscript_import
    Then the import is aborted with ManuscriptParseError
    And no excessive memory is used

  @p0
  Scenario: Manuscript exceeds doc-kind page limit warns
    Given a manuscript producing 60 pages and doc_kind=picture_book (max 48)
    When I manuscript_import
    Then a warning suggests using early_reader
    And the import proceeds (or aborts if user opts)

  @p0
  Scenario: Embedded images become asset library uploads
    Given a DOCX with embedded images
    When I manuscript_import
    Then each image becomes an UploadAsset
    And the user is asked where to place them (no auto-placement)

  @p0
  Scenario: Markdown code blocks render as monospace text + warn
    Given a Markdown manuscript with a fenced code block
    When I manuscript_import
    Then the code block is rendered using a monospace font
    And a warning notes "code in a kids' book"

  @p0
  Scenario: Scene-break heuristic capped at 1 illustration per page
    Given a manuscript with many breaks (one per paragraph)
    When I manuscript_import
    Then at most 1 illustration slot per page exists

  @p0
  Scenario: Scanned PDF (image-only) rejected in P0
    Given a PDF with no extractable text
    When I manuscript_import
    Then ManuscriptFormatUnsupportedError is raised
    And the error suggests an OCR step

  @p1
  Scenario: PDF (text) imported via pdfplumber
    Given a PDF with embedded text
    When I manuscript_import
    Then text extracted preserves paragraph boundaries
