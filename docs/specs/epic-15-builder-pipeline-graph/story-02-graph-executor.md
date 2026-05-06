# Story 15.2: GraphPipelineExecutor

## User Story

As a **platform developer**, I want a graph-aware executor that drives pipeline
runs to completion, so that stage ordering, skipping, timeout, and failure
halting are all data-driven rather than hardcoded in a monolithic method.

## Background

`BuilderPipeline.execute()` mixes traversal logic, domain-specific skip
conditions, stage dispatching, polling, timeout, spec hooks, and result
assembly into one 180-line method. The executor should only know about
graph traversal and stage dispatching — every other concern belongs in the
node's `skip_if` / `on_complete` callbacks or in the prompt template.

## Type Contracts

```python
class GraphPipelineExecutor:
    def __init__(self, engine: Any) -> None: ...

    async def execute(
        self,
        graph: PipelineGraph,
        run: PipelineRun,
        *,
        auth: Any,
    ) -> PipelineRun:
        """Drive the graph to completion.

        Loop:
          1. Find ready nodes (all deps in completed | skipped).
          2. For each ready node:
             a. Evaluate skip_if(run.context). If True: mark skipped, continue.
             b. Check engine.has_agent(node.agent_name). If False: mark skipped.
             c. Build prompt from node.prompt_template % run.context.
             d. Dispatch via engine. Poll with exponential backoff up to node.timeout_seconds.
             e. On success: write run.context[node.name], call on_complete, mark completed.
             f. On failure / timeout: mark failed, halt — return run immediately.
          3. If no ready nodes remain: graph is done. Return run.

        PipelineRun.status is set to "completed" on success, "failed at <name>" on halt.
        """
```

## Acceptance Criteria

- AC1: Given a single-node graph whose agent returns a result, When `execute` is
  called, Then `run.context[node.name]` contains the agent's output text and
  `run.status == "completed"`.
- AC2: Given A→B linear chain, When `execute` is called, Then A executes before
  B, and B's prompt receives A's output via `run.context["A"]`.
- AC3: Given a node whose `skip_if` returns True, When `execute` is called, Then
  the node is not dispatched to the engine and is added to `skipped`.
- AC4: Given a node whose `skip_if` returns True but whose downstream node has
  no other unsatisfied deps, When `execute` is called, Then the downstream node
  executes (skip counts as satisfied).
- AC5: Given a node whose agent fails, When `execute` is called, Then execution
  halts, `run.status` contains the failed node's name, and no downstream nodes
  are dispatched.
- AC6: Given a node whose engine does not have the required agent, When `execute`
  is called, Then the node is skipped (not failed) and execution continues.
- AC7: Given a node whose dispatch exceeds `timeout_seconds`, When `execute` is
  called, Then the stage is marked failed, the work item is cancelled, and
  execution halts.
- AC8: Given a node with a non-None `on_complete` callback, When the node
  completes successfully, Then `on_complete(run, output_text)` is awaited.
- AC9: Given `on_complete` raises an exception, When `execute` is called, Then
  the exception propagates (on_complete errors are not silently swallowed).
- AC10: Given a graph with two independent entry nodes (no deps), When `execute`
  is called, Then both are dispatched (sequential today; the interface does not
  preclude parallel dispatch in future).

## Gherkin Scenarios

```gherkin
Feature: GraphPipelineExecutor basic execution

  Scenario: Single node executes and stores output
    Given a graph with one node "plan" (no deps, agent "arbiter")
    And the engine returns "my plan text" for "arbiter"
    When execute(graph, run) is called
    Then run.context["plan"] == "my plan text"
    And run.status == "completed"

  Scenario: Linear chain executes in dependency order
    Given a graph: plan → code (depends_on=["plan"])
    And the engine returns "plan output" for plan, "code output" for code
    When execute(graph, run) is called
    Then "plan output" appears in the prompt sent to code
    And run.context["plan"] == "plan output"
    And run.context["code"] == "code output"

  Scenario: skip_if=True skips dispatch
    Given a node "decompose" with skip_if=lambda ctx: True
    When execute(graph, run) is called
    Then engine.dispatch is NOT called for "decompose"
    And "decompose" is in run.skipped_stages

  Scenario: Skipped node's downstream still executes
    Given "decompose" is skipped via skip_if
    And "scaffold" depends_on=["decompose"]
    When execute(graph, run) is called
    Then "scaffold" is dispatched

  Scenario: Agent failure halts execution
    Given a graph: plan → code
    And the engine reports "plan" as failed
    When execute(graph, run) is called
    Then "code" is NOT dispatched
    And run.status contains "plan"

  Scenario: Missing agent is skipped, not failed
    Given node "audit" whose agent_name is not registered
    When execute(graph, run) is called
    Then "audit" is not dispatched
    And run.status is NOT "failed at audit"

  Scenario: Stage timeout halts execution
    Given node "plan" with timeout_seconds=1
    And the engine never completes the work item within 1 second
    When execute(graph, run) is called
    Then run.status contains "plan"
    And engine.cancel was called for the work item

  Scenario: on_complete hook invoked on success
    Given node "plan" with on_complete=my_hook
    When "plan" completes with output "the plan"
    Then my_hook was called with (run, "the plan")
```

## Test Mapping

| AC   | Test path                                   | Test function                                     | Tier     |
|------|---------------------------------------------|---------------------------------------------------|----------|
| AC1  | tests/orchestrator/test_graph_executor.py   | test_single_node_stores_output                    | critical |
| AC2  | tests/orchestrator/test_graph_executor.py   | test_linear_chain_dep_output_in_prompt            | critical |
| AC3  | tests/orchestrator/test_graph_executor.py   | test_skip_if_prevents_dispatch                    | critical |
| AC4  | tests/orchestrator/test_graph_executor.py   | test_skipped_node_satisfies_downstream            | critical |
| AC5  | tests/orchestrator/test_graph_executor.py   | test_agent_failure_halts_execution                | critical |
| AC6  | tests/orchestrator/test_graph_executor.py   | test_missing_agent_skips_not_fails                | happy    |
| AC7  | tests/orchestrator/test_graph_executor.py   | test_timeout_halts_and_cancels                    | critical |
| AC8  | tests/orchestrator/test_graph_executor.py   | test_on_complete_invoked_on_success               | critical |
| AC9  | tests/orchestrator/test_graph_executor.py   | test_on_complete_exception_propagates             | edge     |
| AC10 | tests/orchestrator/test_graph_executor.py   | test_two_independent_entry_nodes_both_dispatched  | happy    |

## Files to Touch

- New: `src/stronghold/orchestrator/executor.py`
- New: `tests/orchestrator/test_graph_executor.py`
