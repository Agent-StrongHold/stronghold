# Epic 15: Builder Pipeline as a Proper Graph

## Problem

`BuilderPipeline.execute()` is a 180-line, E-complexity (score 33) monolith that
models a DAG as a flat list with magic strings and hardcoded conditionals:

```python
if stage.skip_if == "atomic" and skip_decompose: ...
if stage.skip_if == "review_clean" and any(s in prev_output ...): ...
if stage.name == "decompose" and spec is None and ...: ...
if stage.name == "scaffold" and spec is not None: ...
```

This is the wrong abstraction. Skip conditions are predicates, not strings.
Post-completion hooks are data, not `if stage.name ==` branches. Data flow between
stages is a graph edge, not a single `prev_output` string threaded through a loop.
Adding a new stage that depends on two upstream stages is structurally impossible
without touching the executor. Parallel execution of independent stages is
impossible because the model is inherently sequential.

## Solution

Replace the list-with-magic-strings model with a proper DAG:

- **`PipelineNode`** — declares explicit `depends_on`, a `skip_if` predicate, an
  `on_complete` async hook, and a timeout.
- **`PipelineGraph`** — holds the node set, resolves ready nodes, validates the DAG
  (cycles, orphans, undeclared deps).
- **`GraphPipelineExecutor`** — drives execution: find ready nodes → check skip →
  dispatch → poll → store output → repeat.
- **`RunContext`** — `dict[str, str]` mapping `node_name → output`, replacing the
  `prev_output` string. Prompt templates reference upstream outputs by name.

This aligns with the `FlowSpec` / `NodeSpec` declarative graph model described in
ARCHITECTURE.md §15.3 (CFM-3). `PipelineNode` is the runtime-concrete forerunner
of `NodeSpec`; `PipelineGraph` is the runtime forerunner of `FlowSpec`.

## Invariants

| ID | Statement |
|----|-----------|
| INV-01 | A node only becomes ready when every node in `depends_on` is in `completed ∪ skipped`. |
| INV-02 | A failed node is never added to `completed` or `skipped`. No downstream node can become ready after a failure. |
| INV-03 | A skipped node satisfies the dependency requirement for its dependents. |
| INV-04 | `RunContext[node.name]` is written exactly once, after the node completes successfully. |
| INV-05 | A graph with a cycle fails validation before any execution begins. |
| INV-06 | A graph with an undeclared dependency (node references a name not in the graph) fails validation. |
| INV-07 | Execution halts after the first node failure. Pending and ready nodes do not execute. |
| INV-08 | `on_complete` is awaited with `(run, output_text)` immediately after `RunContext` is updated. |
| INV-09 | Timeout expiry cancels the dispatched work item and marks the stage failed — it does not execute `on_complete`. |

## Stories

| Story | Title | Status |
|-------|-------|--------|
| 15.1 | `PipelineNode` + `PipelineGraph` data model | pending |
| 15.2 | `GraphPipelineExecutor` | pending |
| 15.3 | Migrate `BUILDER_PIPELINE` list to graph nodes | pending |

## Files Introduced

| Path | Purpose |
|------|---------|
| `src/stronghold/orchestrator/graph.py` | `PipelineNode`, `PipelineGraph`, `RunContext` |
| `src/stronghold/orchestrator/executor.py` | `GraphPipelineExecutor` |
| `tests/orchestrator/test_pipeline_graph.py` | Graph data model + validation tests |
| `tests/orchestrator/test_graph_executor.py` | Executor behaviour tests |

## Files Modified

| Path | Change |
|------|--------|
| `src/stronghold/orchestrator/pipeline.py` | Replace `PipelineStage` list + `execute()` with graph nodes; keep `BuilderPipeline` as the public API |
| `ARCHITECTURE.md` | Add §16 documenting this model |
