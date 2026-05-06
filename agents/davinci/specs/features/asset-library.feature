Feature: Asset library
  Tenant-scoped library of characters, props, and uploads with embedding-
  based search and drag-onto-canvas.

  See ../18-asset-library.md.

  Background:
    Given an authenticated user "alice" in tenant "acme"

  @p0 @critical
  Scenario: Save a character from a layer plus reference sheet
    Given a Layer "L1" containing a character
    And a Layer "Ref" containing a multi-view reference sheet
    When alice asset_save_with_views with name "Lily"
    Then a CharacterAsset is created
    And reference_sheet_blob_ids has multiple entries
    And tags can be set

  @p0
  Scenario: Save a prop from a layer
    Given a Layer "Chest" depicting a wooden chest
    When alice asset_save_from_layer kind=PROP, name="Wooden Chest"
    Then a PropAsset is created
    And isolation_alpha is true after rembg cleanup

  @p0 @critical
  Scenario: Upload an asset (logo)
    Given a logo PNG (Warden-clean)
    When alice asset_upload kind=UPLOAD source_kind=LOGO, rights_acknowledged=true
    Then an UploadAsset is created
    And warden_verdict_id is recorded

  @p0 @security
  Scenario: Upload without rights_acknowledged is rejected
    Given a PNG
    When alice asset_upload with rights_acknowledged=false
    Then AssetUploadValidationError is raised

  @p0 @security
  Scenario: Uploaded SVG with embedded JS has scripts stripped
    Given an SVG with <script> elements
    When asset_upload kind=UPLOAD, source_kind=SVG
    Then the saved SVG has no <script> elements
    And the asset is created

  @p0 @critical
  Scenario: Drag-onto-canvas creates a new layer at clicked position
    Given an existing CharacterAsset
    When alice asset_insert at position (200, 300) on Page P1
    Then a new raster Layer exists with x=200, y=300
    And source.image_bytes equals the asset's primary blob

  @p0
  Scenario: Tag search filters by tags
    Given assets with tags [["fantasy", "warrior"], ["fantasy", "dragon"], ["food"]]
    When alice asset_search with tags=["fantasy"]
    Then both fantasy-tagged assets are returned

  @p0
  Scenario: Substring search by name
    Given an asset named "Lily the Dragon"
    When alice asset_search with mode=substring, query="lily"
    Then the asset is returned

  @p0
  Scenario: Semantic search uses CLIP embeddings
    Given assets with CLIP embeddings stored
    When alice asset_search with mode=semantic, query="cute small dragon"
    Then results are ranked by cosine similarity to the query embedding
    And the top result is the closest match

  @p0
  Scenario: Embedding unavailability is non-fatal
    Given the embedding model is offline
    When alice creates an asset
    Then the asset is created without embedding
    And embedding back-fills when the model is available

  @p0 @security
  Scenario: Cross-tenant asset access denied
    Given an asset owned by tenant "globex"
    When alice (tenant "acme") tries asset_get
    Then AssetNotFoundError is raised

  @p0
  Scenario: Hard-delete blocked while in use
    Given an asset referenced by 2 documents
    When alice asset_delete (hard)
    Then AssetReferenceInUseError is raised
    And asset_archive (soft) is offered as alternative

  @p0
  Scenario: Asset version evolution does not auto-rewrite old documents
    Given an asset used in Document D1
    When the asset's primary blob is replaced (refined)
    Then D1's existing layer keeps its prior blob reference
    Unless D1.metadata.auto_update_assets is true

  @p1 @perf
  Scenario: Semantic search over 10k assets returns within budget
    Given 10k assets with embeddings indexed via HNSW
    When alice asset_search semantic with a query
    Then the search completes in under 100 ms
