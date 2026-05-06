Feature: Versioning and history
  Append-only DocumentVersion log; checkpoints before risky ops; revert
  produces a new version branching from any prior; deltas + snapshots
  bound restore cost.

  See ../23-versioning.md.

  Background:
    Given an authenticated user in tenant "acme"
    And a Document "D1" with one Page and one Layer

  @p0 @critical
  Scenario: Each mutation creates a new DocumentVersion
    When I update the Layer's text content 3 times
    Then 3 new DocumentVersions exist
    And ordinals are sequential
    And each parent_version_id points at the prior

  @p0 @critical
  Scenario: Restore to a prior version reproduces that exact state
    Given I record the Document state at version 3
    And I make 5 more changes
    When I version_get version 3
    Then the restored state byte-equals the recorded state at version 3

  @p0
  Scenario: Snapshot intervals cap restore cost
    Given a 50-version history with snapshot interval 25
    When I version_get version 1
    Then restore = nearest snapshot ≤ 1 + apply forward deltas
    And the operation completes in under 500ms

  @p0
  Scenario: Revert produces a new version branching from prior
    Given a Document at version 10
    When I revert to version 5
    Then a new version 11 exists with parent_version_id = 5
    And HEAD points to version 11
    And version 10 is still reachable

  @p0 @critical
  Scenario: Checkpoint creates a snapshot version
    When I checkpoint_create with name "before-regen", message "..."
    Then a new DocumentVersion exists with snapshot_blob_id non-null
    And the version's message contains "before-regen"

  @p0
  Scenario: Pre-regen auto-checkpoint before inpaint
    When I inpaint Layer "L1"
    Then a checkpoint version exists immediately before the inpaint version
    And its message references "pre_regen"

  @p0
  Scenario: Coalescing of rapid same-author same-layer ops
    When I toggle an effect on Layer "L1" 5 times within 5 seconds
    Then the version log shows 1 (or fewer) coalesced versions, not 5

  @p0
  Scenario: User-authored vs agent-authored versions distinguished
    Given alice manually edits a text layer (USER)
    And the agent regenerates a background layer (AGENT)
    When I list versions
    Then both versions exist with their author_kind correctly set

  @p0
  Scenario Outline: Op kinds round-trip
    When I perform <op> on the document
    Then a new version exists with delta containing <op_kind>

    Examples:
      | op                                  | op_kind             |
      | add a page                          | page_added          |
      | delete a page                       | page_deleted        |
      | reorder pages                       | page_reordered      |
      | add a layer                         | layer_added         |
      | update a layer                      | layer_updated       |
      | delete a layer                      | layer_deleted       |
      | change effect stack on a layer      | effect_changed      |
      | change document metadata            | doc_meta_changed    |

  @p0 @security
  Scenario: Cross-tenant version_get returns nothing
    Given user bob in tenant "globex" owns Document "B1" with versions
    When alice (tenant "acme") tries version_get on B1's version
    Then VersionNotFoundError is raised

  @p0
  Scenario: Blob retention defers deletion until no version references it
    Given an old version references blob "B1"
    When the current page no longer references blob "B1"
    Then "B1" is NOT deleted as long as the old version exists

  @p0
  Scenario: Retention removes versions older than policy
    Given a Document with 250 versions older than 90 days
    And only 200 versions retained per policy
    When the retention sweep runs
    Then exactly the surplus older non-checkpoint versions are removed
    And checkpoints are preserved

  @p0
  Scenario: Pinned versions never garbage-collected
    Given a regular version pinned by the user
    When retention sweep runs after years
    Then the pinned version is still present

  @p0
  Scenario: Diff between two versions reports structured ops
    Given two versions A (older) and B (newer)
    When I version_diff A and B
    Then the response lists VersionOps from A→B

  @p1
  Scenario: Side-by-side rendered comparison
    When I version_compare_render A B page p
    Then the response includes two PNG renders, one per version

  @p1 @perf
  Scenario: Restore from 1k-op history within budget
    Given a 1000-op history with snapshots every 25 ops
    When I version_get the latest
    Then the call completes in under 500 ms
