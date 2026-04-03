# Builders 2.0 Test Master Plan

## Purpose

This document defines the future-state test suite for Builders 2.0 before large implementation changes begin.

The rule is simple:

- the target architecture is not done when code exists
- the target architecture is done when the full test suite exists and passes

This suite must include both:

- behavioral tests
- evidence-based tests that prove the soundness of the architecture

Only after the target suite is defined do we start major code movement and deletion.

## Done Definition

Builders 2.0 is considered complete when all of the following are true:

- all new Builders 2.0 acceptance criteria have explicit tests
- the complete target Builders 2.0 suite exists
- every new test is either implemented or deliberately stubbed with a named gap
- all Builders 2.0 critical, happy-path, integration, resilience, and end-to-end tests pass
- evidence-based tests pass for architecture soundness
- legacy tests are classified as `keep`, `rewrite`, or `delete`
- no legacy test remains ambiguous in ownership

## Core Acceptance Criteria

### Architecture

- Stronghold core runs without importing Builders runtime code in-process
- Builders runtime is deployed and versioned separately from Stronghold core
- Frank, Mason, and Auditor share one Builders runtime
- generic GitAgent-style agents remain on a separate generic runtime
- workflow state is owned by Stronghold core, not Builders runtime
- Builders runtime is stateless across requests

### Orchestration

- Stronghold core creates, persists, resumes, and finishes builder runs
- Stronghold core decides stage advancement
- Builders runtime produces artifacts and claims only
- a run can deterministically become `completed`, `failed`, or `blocked`
- retries and loopbacks are owned by Stronghold core

### Delivery Workflow

- an issue can flow to acceptance criteria, tests, implementation, validation, and PR
- Frank produces explicit acceptance criteria and test artifacts
- Mason produces implementation and validation artifacts
- CI pass is required before completion
- coverage `>= 85%` is required before completion
- coding-practice checks are enforced before completion

### PR Audit Workflow

- a PR can trigger an audit workflow
- Auditor produces durable audit artifacts
- Auditor can pass, block, or request rework
- audit results can loop work back to Mason
- audit decisions are surfaced in UI and GitHub

### Learning Workflow

- structured audit findings become durable learning artifacts
- learnings can target `mason`, `frank`, or `builders_workflow`
- future Builders runs load relevant learnings
- trend tracking measures whether violation rates improve over time

### Reporting

- UI updates exist for each stage
- GitHub issue updates exist for each stage
- stage logs and artifacts are traceable
- progress survives runtime restart

### Reliability

- Builders runtime restart does not lose run state
- stage replays are idempotent where required
- version skew between core and runtime is handled explicitly
- artifact lineage remains intact across retries

## Evidence-Based Testing Rule

A significant portion of this suite must be evidence-based.

Evidence-based means the test proves a system property, not just that a code path executed.

Examples:

- proving workflow state survives runtime restart
- proving core, not runtime, owns advancement decisions
- proving two runtime versions can both satisfy the same contract
- proving artifact handoff preserves lineage across retries
- proving GitHub progress updates are replace/update-safe instead of spammy
- proving coverage gating is deterministic and not LLM-judged

Each major acceptance criterion should have:

- behavioral test
- evidence-based test
- failure-mode test

## Test Suite Structure

```text
tests/
  /builders
    /contracts
    /core
    /runtime
    /services
    /integration
    /resilience
    /evidence
    /e2e
```

## Suite Categories

### 1. Contracts

Purpose:

- lock the wire format between Stronghold core and Builders runtime

Requirements:

- request schema validation
- response schema validation
- artifact schema validation
- version compatibility checks
- unknown-field and missing-field handling

Evidence expectations:

- prove runtime version N and N+1 can both satisfy contract rules where intended

Target files:

- `tests/builders/contracts/test_run_request.py`
- `tests/builders/contracts/test_run_result.py`
- `tests/builders/contracts/test_artifact_ref.py`
- `tests/builders/contracts/test_stage_event.py`
- `tests/builders/contracts/test_worker_status.py`
- `tests/builders/contracts/test_version_compatibility.py`

### 2. Core

Purpose:

- verify that orchestration logic lives in Stronghold core

Requirements:

- run creation
- state persistence
- stage transition rules
- retry scheduling
- blocked/fail/complete classification
- gate evaluation ownership

Evidence expectations:

- prove core advances stages even when runtime only returns claims
- prove runtime cannot self-declare completion without gate satisfaction

Target files:

- `tests/builders/core/test_run_creation.py`
- `tests/builders/core/test_stage_transitions.py`
- `tests/builders/core/test_gate_ownership.py`
- `tests/builders/core/test_retry_policy.py`
- `tests/builders/core/test_blocked_run.py`
- `tests/builders/core/test_completion_rules.py`
- `tests/builders/core/test_resume_state.py`

### 3. Runtime

Purpose:

- verify Builders runtime behavior for shared Frank/Mason/Auditor execution

Requirements:

- role selection
- stage dispatch
- prompt loading by role/stage/version
- tool allowlist by role/stage
- stateless request handling
- artifact production

Evidence expectations:

- prove Frank, Mason, and Auditor share runtime infrastructure while remaining logically distinct
- prove no durable workflow state is retained in runtime memory

Target files:

- `tests/builders/runtime/test_role_selection.py`
- `tests/builders/runtime/test_stage_dispatch.py`
- `tests/builders/runtime/test_frank_prompt_loading.py`
- `tests/builders/runtime/test_mason_prompt_loading.py`
- `tests/builders/runtime/test_auditor_prompt_loading.py`
- `tests/builders/runtime/test_tool_allowlists.py`
- `tests/builders/runtime/test_artifact_production.py`
- `tests/builders/runtime/test_statelessness.py`

### 4. Services

Purpose:

- verify the platform services Builders depends on

Requirements:

- workspace creation
- workspace reuse and cleanup
- GitHub issue update behavior
- PR creation/update behavior
- artifact persistence/retrieval
- event publication

Evidence expectations:

- prove GitHub updates are safe to replay
- prove workspace refs remain stable across retries
- prove artifact refs are durable and immutable where required

Target files:

- `tests/builders/services/test_workspace_service.py`
- `tests/builders/services/test_workspace_cleanup.py`
- `tests/builders/services/test_github_issue_updates.py`
- `tests/builders/services/test_github_pr_lifecycle.py`
- `tests/builders/services/test_artifact_store.py`
- `tests/builders/services/test_event_bus.py`

### 5. Integration

Purpose:

- verify service boundaries between core, runtime, and supporting services

Requirements:

- core to runtime request/response flow
- runtime to workspace/GitHub/artifact service flow
- artifact handoff from Frank stage to Mason stage
- audit artifact handoff into learning flow
- gate evaluation after runtime result

Evidence expectations:

- prove role outputs are consumed through artifacts and contracts, not shared memory

Target files:

- `tests/builders/integration/test_core_to_runtime.py`
- `tests/builders/integration/test_runtime_to_workspace.py`
- `tests/builders/integration/test_runtime_to_github.py`
- `tests/builders/integration/test_runtime_to_artifact_store.py`
- `tests/builders/integration/test_frank_to_mason_handoff.py`
- `tests/builders/integration/test_audit_to_learning_handoff.py`
- `tests/builders/integration/test_gate_after_result.py`

### 6. Resilience

Purpose:

- verify restart, replay, retry, and failure recovery behavior

Requirements:

- runtime restart during a run
- core restart with persisted run state
- retry after transient failure
- idempotent replay of stage update
- loopback from Mason to Frank
- loopback from Auditor to Mason

Evidence expectations:

- prove a run survives runtime restart
- prove repeated event delivery does not corrupt state
- prove retries do not duplicate artifacts or GitHub spam

Target files:

- `tests/builders/resilience/test_runtime_restart_recovery.py`
- `tests/builders/resilience/test_core_restart_recovery.py`
- `tests/builders/resilience/test_stage_replay_idempotency.py`
- `tests/builders/resilience/test_retry_without_duplicate_artifacts.py`
- `tests/builders/resilience/test_retry_without_duplicate_issue_comments.py`
- `tests/builders/resilience/test_mason_to_frank_loopback.py`
- `tests/builders/resilience/test_auditor_to_mason_loopback.py`

### 7. Evidence

Purpose:

- explicitly prove architecture soundness properties

These are not convenience tests. These are proof-oriented tests.

Required evidence properties:

- core owns truth
- runtime is stateless
- artifacts are the only handoff boundary
- versioned runtimes can be rolled independently
- coverage gate is deterministic
- CI gate is deterministic
- progress reporting survives failure/restart
- learning targets are correctly attributed

Target files:

- `tests/builders/evidence/test_core_owns_truth.py`
- `tests/builders/evidence/test_runtime_is_stateless.py`
- `tests/builders/evidence/test_artifact_lineage.py`
- `tests/builders/evidence/test_version_skew_compatibility.py`
- `tests/builders/evidence/test_coverage_gate_is_deterministic.py`
- `tests/builders/evidence/test_ci_gate_is_deterministic.py`
- `tests/builders/evidence/test_progress_survives_restart.py`
- `tests/builders/evidence/test_learning_target_attribution.py`

### 8. End-to-End

Purpose:

- prove the whole issue-to-PR architecture works as a system

Requirements:

- happy path issue to PR
- spec revision loop
- PR audit pass
- PR audit rework loop
- blocked run
- failed run
- resumed run after runtime restart
- versioned runtime swap with core still up

Target files:

- `tests/builders/e2e/test_issue_to_pr_happy_path.py`
- `tests/builders/e2e/test_spec_revision_loop.py`
- `tests/builders/e2e/test_pr_audit_pass.py`
- `tests/builders/e2e/test_pr_audit_rework_loop.py`
- `tests/builders/e2e/test_blocked_run.py`
- `tests/builders/e2e/test_failed_run.py`
- `tests/builders/e2e/test_resume_after_runtime_restart.py`
- `tests/builders/e2e/test_runtime_version_swap.py`

## Marker Strategy

Add new markers:

- `builders_critical`
- `builders_happy`
- `builders_integration`
- `builders_resilience`
- `builders_evidence`
- `builders_e2e`

Meaning:

- `builders_critical`: contract and core invariants that must pass on every change
- `builders_happy`: one golden-path per Builders subsystem
- `builders_integration`: boundary tests across services
- `builders_resilience`: restart/replay/retry tests
- `builders_evidence`: proof-oriented architecture tests
- `builders_e2e`: full issue-to-PR flow

## Test Progression Rule

The suite is built in this order:

1. contracts
2. core
3. runtime
4. services
5. integration
6. resilience
7. evidence
8. e2e

No major code deletion begins until:

- the file layout exists
- the test names exist
- each test file has an owner and purpose

## Stub Policy

Stubbed tests are allowed at the beginning, but they must:

- exist in the final file layout
- name the exact future behavior
- include a short TODO describing the proof or behavior required

Not allowed:

- ambiguous placeholder tests
- unnamed “future work”
- stubs with no mapped acceptance criterion

## Legacy Suite Disposition Model

Every existing test must be classified as:

- `keep`
- `rewrite`
- `delete`

Definitions:

- `keep`: still tests a valid platform invariant in the new architecture
- `rewrite`: concept still matters, but test targets the old embedded Frank/Mason model
- `delete`: obsolete because it tests a removed architecture

## Initial Legacy Guidance

Likely `keep`:

- auth
- security
- quota
- tracing
- prompt store
- generic routing
- generic agent runtime behavior
- workspace/file/tool service tests that still apply

Likely `rewrite`:

- `tests/api/test_mason_routes.py`
- `tests/agents/mason/*`
- `tests/agents/test_github_flow.py`
- `tests/integration/test_full_pipeline_e2e.py` where it assumes embedded builders flow

Likely `delete`:

- tests that only prove old in-process Frank/Mason strategy composition after those modules are removed

## Completion Gate For This Planning Phase

This planning phase is done when:

- the acceptance criteria above are agreed
- the test directory structure is agreed
- the new target test files are listed
- marker strategy is agreed
- legacy tests have a disposition process

Only then do we start:

- writing new implementation
- moving modules
- deleting obsolete code

## Next Step

Create the actual `tests/builders/` directory tree with the full target file set, using minimal stubs where implementation is not ready yet.
