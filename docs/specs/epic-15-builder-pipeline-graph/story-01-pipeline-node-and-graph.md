# Story 15.1: PipelineNode + PipelineGraph Data Model

## User Story

As a **platform developer**, I want pipeline stages expressed as graph nodes with
explicit dependencies, so that I can add, reorder, and parallelize stages without
touching the executor.

## Background

The current `PipelineStage.skip_if` is a magic string matched inside the executor.
`prev_output` is a single string that implicitly carries one upstream's text.
Both force the executor to understand domain logic that belongs in the data model.

## Type Contracts

```python
# RunContext maps node_name → output text produced by that node.
RunContext = dict[str, str]

@dataclass(frozen=True)
class PipelineNode:
    name: str
    agent_name: str
    prompt_template: str          # may reference {context[name]} for any dep
    depends_on: tuple[str, ...]   # names of upstream nodes; empty = entry node
    skip_if: Callable[[RunContext], bool] | None = None
    timeout_seconds: float = 600.0
    on_complete: Callable[[Any, str], Awaitable[None]] | None = None
    # on_complete signature: async (run: PipelineRun, output_text: str) -> None

class PipelineGraph:
    def __init__(self, nodes: Iterable[PipelineNode]) -> None: ...

    def ready(
        self,
        completed: frozenset[str],
        skipped: frozenset[str],
    ) -> list[PipelineNode]:
        """Nodes whose every dependency is in completed | skipped,
        and which are not themselves already in completed | skipped."""

    def validate(self) -> list[str]:
        """Return a list of error strings.
        Empty list means the graph is valid.
        Checks: cycles, undeclared deps, duplicate names."""

    def __len__(self) -> int: ...
    def __contains__(self, name: str) -> bool: ...
```

## Acceptance Criteria

- AC1: Given a node with `depends_on=()`, When `ready({}, {})` is called, Then
  it is included in the result.
- AC2: Given a node B with `depends_on=("A",)`, When A is in `completed`, Then
  B is included in `ready(completed, skipped)`.
- AC3: Given a node B with `depends_on=("A",)`, When A is in `skipped`, Then
  B is included in `ready(completed, skipped)` (skipped counts as satisfied).
- AC4: Given a node B with `depends_on=("A",)`, When A is in neither set, Then
  B is NOT in `ready(completed, skipped)`.
- AC5: Given a node B with `depends_on=("A", "C")`, When only A is completed,
  Then B is NOT ready (all deps required).
- AC6: Given a node already in `completed`, When `ready` is called, Then it is
  NOT returned again (no re-execution).
- AC7: Given a graph A→B→C (linear chain), When `validate()` is called, Then
  the result is an empty list.
- AC8: Given a graph with a cycle A→B→A, When `validate()` is called, Then
  the result contains at least one error string mentioning the cycle.
- AC9: Given a node referencing a dependency name not in the graph, When
  `validate()` is called, Then the result contains an error mentioning the
  undeclared dependency.
- AC10: Given two nodes with the same name, When `PipelineGraph` is constructed,
  Then a `ValueError` is raised immediately (not deferred to validate).

## Gherkin Scenarios

```gherkin
Feature: PipelineGraph dependency resolution

  Background:
    Given nodes: "plan" (no deps), "code" (depends_on=["plan"]), "review" (depends_on=["code"])

  Scenario: Entry node is ready immediately
    When ready(completed={}, skipped={})
    Then result contains "plan"
    And result does not contain "code" or "review"

  Scenario: Node becomes ready after dependency completes
    When ready(completed={"plan"}, skipped={})
    Then result contains "code"
    And result does not contain "review"

  Scenario: Skipped dependency satisfies dependent
    When ready(completed={}, skipped={"plan"})
    Then result contains "code"

  Scenario: All dependencies must be satisfied
    Given "merge" depends_on=["code", "review"]
    When ready(completed={"code"}, skipped={})
    Then result does not contain "merge"

  Scenario: Completed node is not returned again
    When ready(completed={"plan"}, skipped={})
    Then result does not contain "plan"

  Scenario: Full chain resolves in order
    When stepping through completion:
      | step | completed_after |
      | 1    | plan            |
      | 2    | plan, code      |
      | 3    | plan, code, review |
    Then at step 1, ready = ["code"]
    And at step 2, ready = ["review"]
    And at step 3, ready = []

Feature: PipelineGraph validation

  Scenario: Valid linear graph passes
    Given A→B→C
    When validate()
    Then errors = []

  Scenario: Direct cycle detected
    Given A depends_on B, B depends_on A
    When validate()
    Then errors is non-empty
    And at least one error mentions "cycle"

  Scenario: Indirect cycle detected
    Given A→B→C→A
    When validate()
    Then errors is non-empty

  Scenario: Undeclared dependency detected
    Given node "B" declares depends_on=["ghost"] but "ghost" is not in the graph
    When validate()
    Then errors contains a message mentioning "ghost"

  Scenario: Duplicate node name raises immediately
    Given two nodes both named "plan"
    When constructing PipelineGraph
    Then ValueError is raised
```

## Test Mapping

| AC   | Test path                                  | Test function                                    | Tier     |
|------|--------------------------------------------|--------------------------------------------------|----------|
| AC1  | tests/orchestrator/test_pipeline_graph.py  | test_entry_node_ready_with_no_completed          | critical |
| AC2  | tests/orchestrator/test_pipeline_graph.py  | test_node_ready_after_dep_completed              | critical |
| AC3  | tests/orchestrator/test_pipeline_graph.py  | test_skipped_dep_satisfies_dependent             | critical |
| AC4  | tests/orchestrator/test_pipeline_graph.py  | test_node_not_ready_when_dep_pending             | critical |
| AC5  | tests/orchestrator/test_pipeline_graph.py  | test_all_deps_required                           | critical |
| AC6  | tests/orchestrator/test_pipeline_graph.py  | test_completed_node_not_returned_again           | critical |
| AC7  | tests/orchestrator/test_pipeline_graph.py  | test_valid_linear_graph_passes_validation        | happy    |
| AC8  | tests/orchestrator/test_pipeline_graph.py  | test_cycle_detected_by_validate                  | critical |
| AC9  | tests/orchestrator/test_pipeline_graph.py  | test_undeclared_dep_detected_by_validate         | critical |
| AC10 | tests/orchestrator/test_pipeline_graph.py  | test_duplicate_node_name_raises_on_construction  | critical |

## Files to Touch

- New: `src/stronghold/orchestrator/graph.py`
- New: `tests/orchestrator/test_pipeline_graph.py`
