Feature: Document model
  A Document holds N ordered Pages, each with print spec and ordered Layers.
  Tenant-scoped, persisted, supports master pages.

  See ../02-document-model.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"
    And a clean documents store

  @p0 @critical
  Scenario: Creating a document with no pages
    When alice creates a document of kind "picture_book" named "First Book"
    Then the document exists with 0 pages
    And owner_id is alice's user id
    And tenant_id is acme's tenant id
    And kind is "picture_book"
    And archived is false

  @p0 @critical
  Scenario: Creating a document with N empty pages
    When alice creates a picture_book "Book" with 32 print_specs
    Then the document has 32 pages
    And page orderings are 0, 1, 2, ..., 31
    And each page has 0 layers

  @p0
  Scenario: Adding a page at a position shifts later pages
    Given alice has a 4-page document
    When alice adds a page at ordering 2
    Then the document has 5 pages
    And the new page has ordering 2
    And original pages 2 and 3 now have orderings 3 and 4

  @p0
  Scenario: Reordering pages preserves master page references
    Given alice has a document with master "M1"
    And pages 0..3 reference master "M1" by id
    When alice reorders pages to [3, 2, 1, 0]
    Then every page's master_id is still "M1"

  @p0
  Scenario: Deleting a page renumbers later pages
    Given alice has a 5-page document
    When alice deletes page at ordering 2
    Then the document has 4 pages
    And page orderings are 0, 1, 2, 3 (gapless)

  @p0
  Scenario: Duplicating a page deep-copies layers and effects
    Given alice has a page with 3 layers and an effect on each
    When alice duplicates the page
    Then there are now two pages with identical layer counts
    And the new page's layers have new ids
    And the new layers have effects with new ids matching the originals' params

  @p0 @critical @security
  Scenario: Cross-tenant document read returns nothing
    Given bob in tenant "globex" has document "B1"
    When alice (tenant "acme") tries to open "B1"
    Then DocumentNotFoundError is raised
    And no row from globex is exposed

  @p0 @critical @security
  Scenario: Cross-tenant blob references are rejected
    Given bob in tenant "globex" owns blob "BB1"
    When alice tries to attach "BB1" as a layer source
    Then DocumentNotFoundError or PermissionDeniedError is raised

  @p0
  Scenario: Master deletion blocked while in use
    Given a master page "M1" referenced by page 0
    When alice tries to delete master "M1"
    Then MasterInUseError is raised
    And "M1" still exists

  @p0
  Scenario: Master can be deleted after pages re-master
    Given a master "M1" referenced by pages 0..3
    When alice re-masters all pages to null
    And alice deletes "M1"
    Then "M1" no longer exists

  @p0
  Scenario: Empty document export is rejected
    Given alice has a document with 0 pages
    When alice tries to export
    Then EmptyDocumentError is raised

  @p0 @critical
  Scenario: Layer ordering ties break by ordering field
    Given page "P1" has layers [A z=0, B z=0, C z=0] inserted in that order
    When the page composites
    Then the bottom-to-top stack is A, B, C
    And A's ordering < B's ordering < C's ordering

  @p0 @security
  Scenario: Blob dedupe stops at tenant boundary
    Given alice and bob upload the identical PNG bytes
    Then two blobs exist (one per tenant)
    And alice cannot reach bob's blob via shared sha256

  @p1
  Scenario Outline: Picture book documents enforce even page count on export
    Given alice creates a picture_book with <pages> pages
    When alice exports to PDF
    Then the export <result>

    Examples:
      | pages | result                            |
      | 32    | succeeds                          |
      | 33    | warns: odd page count for binding |
      | 0     | fails with EmptyDocumentError     |

  @p1
  Scenario: Concurrent edit detected via expected_version
    Given alice opens "D1" at version 5
    And bob (same tenant, shared doc) edits "D1" → version 6
    When alice writes a layer change with expected_version=5
    Then ConcurrentEditError is raised

  @p1
  Scenario: Soft archive hides from list but preserves data
    Given alice has 3 documents
    When alice archives one
    Then list_documents returns 2 documents
    And the archived document is still readable by id
    And open + un-archive restores it
