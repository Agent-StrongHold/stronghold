# Story 15.3: Migrate BUILDER_PIPELINE to Graph Nodes

## User Story

As a **platform developer**, I want the existing five-stage builder pipeline
expressed as `PipelineNode` instances in a `PipelineGraph`, so that
`BuilderPipeline.execute()` is deleted and replaced by `GraphPipelineExecutor`.

## Background

The existing pipeline stages and their domain logic:

| Stage | Current skip_if | Current on_complete hook | Current dep |
|-------|----------------|--------------------------|-------------|
| decompose | `"atomic"` string + `skip_decompose` flag | emit spec from prev_output | — (entry) |
| scaffold | — | enrich spec with property tests | decompose |
| code | — | — | scaffold |
| review | `"review_clean"` string matching prev_output | — | code |
| gate | — | — | review |

Each stage's `skip_if` and `on_complete` become typed callables registered on
the `PipelineNode`. The `prompt_template` references `context["decompose"]`,
`context["scaffold"]`, etc. via Python format strings instead of `prev_output`.

## Acceptance Criteria

- AC1: `BuilderPipeline.execute()` is deleted. The class delegates to
  `GraphPipelineExecutor`.
- AC2: The "decompose" stage's `skip_if` is a callable that checks whether
  `skip_decompose` was True (passed via closure or RunContext flag) — not the
  string `"atomic"`.
- AC3: The "review" stage's `skip_if` is a callable that checks whether the
  "code" stage output contains clean-review signals — not string matching inside
  the executor.
- AC4: The spec emission logic (currently `_emit_and_save_spec`) is in the
  "decompose" node's `on_complete`, not inside `execute()`.
- AC5: The spec enrichment logic (currently `_enrich_spec_with_property_tests`)
  is in the "scaffold" node's `on_complete`.
- AC6: After migration, `radon cc src/stronghold/orchestrator/pipeline.py`
  shows no block at rank D or worse.
- AC7: All tests that exercised `BuilderPipeline.execute()` behaviour continue
  to pass without modification (API is preserved).

## Gherkin Scenarios

```gherkin
Feature: Migrated BuilderPipeline uses graph executor

  Scenario: execute() delegates to GraphPipelineExecutor
    Given a BuilderPipeline with a mock engine
    When execute(issue_number=1, title="test") is called
    Then a PipelineGraph is constructed from BUILDER_PIPELINE nodes
    And GraphPipelineExecutor.execute is invoked

  Scenario: decompose skip_if is a predicate, not a string
    Given skip_decompose=True
    When the graph is constructed
    Then decompose.skip_if(context={}) returns True

  Scenario: review skip_if checks code output content
    Given context["code"] contains "no violations"
    When review.skip_if(context) is evaluated
    Then it returns True (skip review: code was clean)

  Scenario: decompose on_complete emits spec
    Given the "decompose" node completes with output "<spec yaml>"
    When on_complete(run, "<spec yaml>") is called
    Then a Spec is created and stored via spec_store

  Scenario: scaffold on_complete enriches spec with property tests
    Given the "scaffold" node completes
    When on_complete(run, output) is called
    Then spec_store.save is called with an enriched Spec
```

## Test Mapping

| AC   | Test path                                          | Test function                                      | Tier     |
|------|----------------------------------------------------|----------------------------------------------------|----------|
| AC2  | tests/orchestrator/test_pipeline_migration.py      | test_decompose_skip_if_is_callable                 | critical |
| AC3  | tests/orchestrator/test_pipeline_migration.py      | test_review_skip_if_checks_context_content         | critical |
| AC4  | tests/orchestrator/test_pipeline_migration.py      | test_decompose_on_complete_emits_spec              | critical |
| AC5  | tests/orchestrator/test_pipeline_migration.py      | test_scaffold_on_complete_enriches_spec            | critical |
| AC6  | tests/orchestrator/test_pipeline_migration.py      | test_pipeline_py_no_block_worse_than_c             | happy    |
| AC7  | tests/orchestrator/ (existing tests unchanged)     | (regression: existing suite passes)                | critical |

## Files to Touch

- Modify: `src/stronghold/orchestrator/pipeline.py` — replace `BUILDER_PIPELINE`
  list, delete `execute()`, delegate to `GraphPipelineExecutor`
- New: `tests/orchestrator/test_pipeline_migration.py`
