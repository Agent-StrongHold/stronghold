# Builders 2.0 Rewrite Wave 1

## Purpose

This document defines the first rewrite wave from the old embedded Frank/Mason architecture into the new Builders 2.0 suite.

Wave 1 focuses on the highest-value tests that currently prove the old delivery path:

- Mason strategy
- Mason API
- GitHub flow
- full embedded pipeline

These tests should be replaced first because they currently anchor the old design.

## Wave 1 Source Tests

- `agents/mason/test_strategy.py`
- `api/test_mason_routes.py`
- `agents/test_github_flow.py`
- `integration/test_full_pipeline_e2e.py`

## Rewrite Rules

- do not port line-for-line behavior from old embedded modules
- preserve the important system invariants
- move orchestration assertions into `tests/builders/core/`
- move runtime execution assertions into `tests/builders/runtime/`
- move service boundary assertions into `tests/builders/integration/` and `tests/builders/services/`
- move architecture proof assertions into `tests/builders/evidence/`
- move user-visible issue-to-PR flow into `tests/builders/e2e/`

## 1. `agents/mason/test_strategy.py`

### Old Purpose

- tested embedded Mason strategy behavior
- mixed fallback behavior, phase execution, tool calls, and gate checks into one in-process strategy object

### New Purpose

Split the concerns:

- runtime dispatch behavior
- runtime artifact production
- core gate ownership
- evidence that runtime is not the workflow owner

### Rewrite Targets

- `tests/builders/runtime/test_role_selection.py`
- `tests/builders/runtime/test_stage_dispatch.py`
- `tests/builders/runtime/test_artifact_production.py`
- `tests/builders/runtime/test_tool_allowlists.py`
- `tests/builders/core/test_gate_ownership.py`
- `tests/builders/evidence/test_core_owns_truth.py`
- `tests/builders/evidence/test_runtime_is_stateless.py`

### What Must Be Preserved

- Frank/Mason role execution can vary by stage
- gate satisfaction is still checked
- tool access is still observable
- the system can handle retry-style iteration

### What Must Not Be Preserved

- direct dependency on in-process `MasonStrategy`
- “done” being decided inside the runtime object

## 2. `api/test_mason_routes.py`

### Old Purpose

- tested Mason assignment and queue routes inside Stronghold
- assumed embedded queue state and background dispatch from the API layer

### New Purpose

Split into:

- Builders API contract tests
- service integration tests
- run-state tests in core

### Rewrite Targets

- `tests/builders/core/test_run_creation.py`
- `tests/builders/core/test_stage_transitions.py`
- `tests/builders/services/test_github_issue_updates.py`
- `tests/builders/services/test_event_bus.py`
- `tests/builders/integration/test_core_to_runtime.py`
- `tests/builders/integration/test_gate_after_result.py`

### What Must Be Preserved

- issue assignment creates a durable run
- workflow progress can be queried
- webhook-triggered work enters the system safely

### What Must Change

- no Mason-specific embedded queue API assumption
- no in-process reactor/queue ownership for Builders runtime state

## 3. `agents/test_github_flow.py`

### Old Purpose

- tested issue-driven GitHub code workflow through the old architecture

### New Purpose

- test Builders handoff and GitHub side effects through service boundaries

### Rewrite Targets

- `tests/builders/integration/test_runtime_to_github.py`
- `tests/builders/integration/test_frank_to_mason_handoff.py`
- `tests/builders/services/test_github_pr_lifecycle.py`
- `tests/builders/services/test_github_issue_updates.py`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py`

### What Must Be Preserved

- issue context drives work
- branches/PRs/issues stay linked
- status reporting is visible during the run

## 4. `integration/test_full_pipeline_e2e.py`

### Old Purpose

- tested embedded end-to-end request pipeline

### New Purpose

- prove full Builders issue-to-PR flow through the new architecture

### Rewrite Targets

- `tests/builders/e2e/test_issue_to_pr_happy_path.py`
- `tests/builders/e2e/test_spec_revision_loop.py`
- `tests/builders/e2e/test_failed_run.py`
- `tests/builders/e2e/test_blocked_run.py`
- `tests/builders/e2e/test_resume_after_runtime_restart.py`
- `tests/builders/e2e/test_runtime_version_swap.py`

### What Must Be Preserved

- issue input becomes real delivery work
- system reports progress through the whole run
- final state is deterministic

### New Requirements To Add

- runtime restart recovery
- versioned runtime swap
- artifact lineage across stage boundaries

## Wave 1 Delivery Order

Implement in this order:

1. `tests/builders/core/test_run_creation.py`
2. `tests/builders/core/test_stage_transitions.py`
3. `tests/builders/core/test_gate_ownership.py`
4. `tests/builders/runtime/test_role_selection.py`
5. `tests/builders/runtime/test_stage_dispatch.py`
6. `tests/builders/integration/test_core_to_runtime.py`
7. `tests/builders/integration/test_frank_to_mason_handoff.py`
8. `tests/builders/services/test_github_issue_updates.py`
9. `tests/builders/services/test_github_pr_lifecycle.py`
10. `tests/builders/e2e/test_issue_to_pr_happy_path.py`

This order establishes:

- state ownership
- runtime boundary
- handoff boundary
- user-visible behavior

## Deletion Condition For Wave 1 Source Tests

The source test can be deleted only when:

- the replacement tests exist
- the replacement tests are real, not stubs
- the replacement tests pass
- the old test proves only obsolete architecture

## Immediate Next Coding Target

The first real test to implement should be:

- `tests/builders/core/test_run_creation.py`

Reason:

- run creation is the root invariant for the whole architecture
