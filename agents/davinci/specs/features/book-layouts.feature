Feature: Book and page layouts
  Catalogued layouts (full-bleed, art-with-caption, cover, etc.) with
  named slots; layout_apply re-positions layers; verso/recto-aware
  master pages; pagination helpers.

  See ../10-book-layouts.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"

  @p0 @critical
  Scenario Outline: Each LayoutKind defines a non-empty slot list
    When I describe layout <kind>
    Then the slot list is non-empty
    And every slot's bbox is within the page bounds (assuming default page size)

    Examples:
      | kind                |
      | FULL_BLEED          |
      | ART_WITH_CAPTION    |
      | ART_WITH_BODY       |
      | DOUBLE_SPREAD       |
      | TEXT_ONLY           |
      | VIGNETTE            |
      | COVER               |
      | TITLE_PAGE          |
      | COPYRIGHT_PAGE      |
      | DEDICATION_PAGE     |
      | POSTER              |
      | INFOGRAPHIC_GRID    |
      | INFOGRAPHIC_FLOW    |

  @p0 @critical
  Scenario: Apply COVER to an empty Page creates required layers
    Given an empty Page
    When I layout_apply COVER
    Then layers exist for slots: title, subtitle, byline, hero_art
    And Page.layout_kind is COVER

  @p0
  Scenario: Apply layout to a Page with matching slot ids re-positions, not duplicates
    Given a Page with 3 layers tagged with slot_ids "title", "subtitle", "byline"
    When I layout_apply TITLE_PAGE
    Then no new layers are added
    And existing layers' x/y/width/height are repositioned to slot bboxes

  @p0
  Scenario: Apply layout with extra non-slot layers preserves them as free
    Given a Page with one slot layer + 2 free layers
    When I layout_apply ART_WITH_CAPTION
    Then the free layers remain on the page (marked free in metadata)
    And a warning is emitted

  @p0
  Scenario: Pagination per AgeBand uses correct words-per-page
    Given a 6000-word manuscript and age_band 5_7 (60 wpp default)
    When I auto_paginate with layout ART_WITH_BODY
    Then approximately 100 pages are produced (within ±10)
    And no page breaks mid-sentence

  @p0
  Scenario: CHAPTER_BREAK forces a new page with TEXT_ONLY layout
    Given a manuscript with explicit CHAPTER_BREAK markers
    When I auto_paginate
    Then each break starts a new TEXT_ONLY chapter-start page

  @p0
  Scenario: Verso/recto master pages mirror gutter margins
    Given a master page "M1" with binding_edge=24, outer_edge=12
    When applied to verso (even ordering) and recto (odd ordering)
    Then the binding edge is on the right for verso, left for recto

  @p0
  Scenario: Page furniture fills slots from doc metadata
    Given a Document with metadata title="My Book", author="Alice", isbn="978-..."
    And a Page with COPYRIGHT_PAGE layout
    When I page_furniture_apply
    Then the page's text layers contain the metadata values

  @p0
  Scenario: Picture book with odd page count → preflight WARN
    Given a picture_book Document with 33 pages
    When preflight runs
    Then page_count_parity WARNs

  @p0
  Scenario: Re-apply same layout is idempotent
    Given a Page with ART_WITH_CAPTION applied
    When I layout_apply ART_WITH_CAPTION again
    Then no new layers are added
    And slot positions match the layout's spec

  @p0
  Scenario: Auto-paginate is idempotent for unchanged input
    Given a manuscript M and age_band 5_7
    When I auto_paginate M, then re-paginate with same input
    Then the second result equals the first
