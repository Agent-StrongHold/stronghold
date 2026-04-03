# Builders 2.0 Traceability Matrix

## Purpose

This document maps Builders 2.0 acceptance criteria to concrete test files.

The goal is simple:

- every acceptance criterion has tests
- every important test proves a criterion
- “done” is measurable

## Status Keys

- `stubbed`: test file exists but only as a placeholder
- `real`: test is implemented
- `future`: test file not yet created

At this stage, the listed Builders tests are mostly `stubbed`.

## AC-1 Stronghold Core Does Not Import Builders Runtime In-Process

Description:

- Builders must be an external runtime boundary, not embedded logic in the main app

Tests:

- `tests/builders/evidence/test_core_owns_truth.py` — `stubbed`
- `tests/builders/integration/test_core_to_runtime.py` — `stubbed`
- `tests/builders/evidence/test_version_skew_compatibility.py` — `stubbed`

## AC-2 Builders Runtime Is Separately Deployable And Versioned

Description:

- Builders runtime must have an independent release/deploy path

Tests:

- `tests/builders/contracts/test_version_compatibility.py` — `stubbed`
- `tests/builders/evidence/test_version_skew_compatibility.py` — `stubbed`
- `tests/builders/e2e/test_runtime_version_swap.py` — `stubbed`

## AC-3 Frank And Mason Share One Runtime But Remain Distinct Roles

Description:

- one Builders runtime image
- distinct role behavior for Frank and Mason

Tests:

- `tests/builders/runtime/test_role_selection.py` — `stubbed`
- `tests/builders/runtime/test_stage_dispatch.py` — `stubbed`
- `tests/builders/runtime/test_frank_prompt_loading.py` — `stubbed`
- `tests/builders/runtime/test_mason_prompt_loading.py` — `stubbed`
- `tests/builders/runtime/test_tool_allowlists.py` — `stubbed`

## AC-4 Workflow State Is Owned By Core

Description:

- Builders runtime returns work products
- core decides advancement and status

Tests:

- `tests/builders/core/test_run_creation.py` — `stubbed`
- `tests/builders/core/test_stage_transitions.py` — `stubbed`
- `tests/builders/core/test_gate_ownership.py` — `stubbed`
- `tests/builders/core/test_completion_rules.py` — `stubbed`
- `tests/builders/evidence/test_core_owns_truth.py` — `stubbed`

## AC-5 Builders Runtime Is Stateless

Description:

- runtime restarts must not destroy workflow state

Tests:

- `tests/builders/runtime/test_statelessness.py` — `stubbed`
- `tests/builders/evidence/test_runtime_is_stateless.py` — `stubbed`
- `tests/builders/resilience/test_runtime_restart_recovery.py` — `stubbed`
- `tests/builders/e2e/test_resume_after_runtime_restart.py` — `stubbed`

## AC-6 Core Can Create, Persist, Resume, And Finish Builder Runs

Description:

- builder runs are first-class durable records

Tests:

- `tests/builders/core/test_run_creation.py` — `stubbed`
- `tests/builders/core/test_resume_state.py` — `stubbed`
- `tests/builders/resilience/test_core_restart_recovery.py` — `stubbed`
- `tests/builders/core/test_completion_rules.py` — `stubbed`

## AC-7 Frank Produces Acceptance Criteria And Test Artifacts

Description:

- Frank must turn the issue into explicit criteria and tests

Tests:

- `tests/builders/runtime/test_artifact_production.py` — `stubbed`
- `tests/builders/runtime/test_frank_prompt_loading.py` — `stubbed`
- `tests/builders/integration/test_frank_to_mason_handoff.py` — `stubbed`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`

## AC-8 Mason Produces Implementation And Validation Artifacts

Description:

- Mason must consume handoff artifacts and produce code/validation outputs

Tests:

- `tests/builders/runtime/test_artifact_production.py` — `stubbed`
- `tests/builders/runtime/test_mason_prompt_loading.py` — `stubbed`
- `tests/builders/integration/test_frank_to_mason_handoff.py` — `stubbed`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`

## AC-9 All Handoffs Use Typed Artifacts

Description:

- no freeform in-memory handoff between Frank and Mason

Tests:

- `tests/builders/contracts/test_artifact_ref.py` — `stubbed`
- `tests/builders/integration/test_frank_to_mason_handoff.py` — `stubbed`
- `tests/builders/evidence/test_artifact_lineage.py` — `stubbed`

## AC-10 Progress Is Visible In UI And GitHub At Each Stage

Description:

- stage updates must be durable and observable

Tests:

- `tests/builders/services/test_github_issue_updates.py` — `stubbed`
- `tests/builders/services/test_event_bus.py` — `stubbed`
- `tests/builders/evidence/test_progress_survives_restart.py` — `stubbed`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`

## AC-11 Retries And Loopbacks Are Deterministic

Description:

- system retry behavior must be explicit and reproducible

Tests:

- `tests/builders/core/test_retry_policy.py` — `stubbed`
- `tests/builders/resilience/test_stage_replay_idempotency.py` — `stubbed`
- `tests/builders/resilience/test_mason_to_frank_loopback.py` — `stubbed`
- `tests/builders/e2e/test_spec_revision_loop.py` — `stubbed`

## AC-12 Runs Can End In Completed, Failed, Or Blocked

Description:

- terminal states must be deterministic and visible

Tests:

- `tests/builders/core/test_blocked_run.py` — `stubbed`
- `tests/builders/core/test_completion_rules.py` — `stubbed`
- `tests/builders/e2e/test_blocked_run.py` — `stubbed`
- `tests/builders/e2e/test_failed_run.py` — `stubbed`

## AC-13 CI Pass Is Required

Description:

- completion requires deterministic CI success

Tests:

- `tests/builders/evidence/test_ci_gate_is_deterministic.py` — `stubbed`
- `tests/builders/core/test_completion_rules.py` — `stubbed`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`

## AC-14 Coverage >= 85 Percent Is Required

Description:

- coverage threshold must be enforced outside LLM judgment

Tests:

- `tests/builders/evidence/test_coverage_gate_is_deterministic.py` — `stubbed`
- `tests/builders/core/test_completion_rules.py` — `stubbed`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`

## AC-15 GitHub PR Lifecycle Is Correct

Description:

- branch and PR operations must stay linked to the run and issue

Tests:

- `tests/builders/services/test_github_pr_lifecycle.py` — `stubbed`
- `tests/builders/integration/test_runtime_to_github.py` — `stubbed`
- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`

## AC-16 Workspace Lifecycle Is Correct

Description:

- workspaces must be created, reused, and cleaned up safely

Tests:

- `tests/builders/services/test_workspace_service.py` — `stubbed`
- `tests/builders/services/test_workspace_cleanup.py` — `stubbed`
- `tests/builders/integration/test_runtime_to_workspace.py` — `stubbed`

## AC-17 Artifact Store Is Durable

Description:

- artifacts must persist across retries and restarts

Tests:

- `tests/builders/services/test_artifact_store.py` — `stubbed`
- `tests/builders/integration/test_runtime_to_artifact_store.py` — `stubbed`
- `tests/builders/evidence/test_artifact_lineage.py` — `stubbed`
- `tests/builders/resilience/test_retry_without_duplicate_artifacts.py` — `stubbed`

## AC-18 Progress Reporting Survives Restart And Replay

Description:

- run visibility must survive system interruptions

Tests:

- `tests/builders/evidence/test_progress_survives_restart.py` — `stubbed`
- `tests/builders/resilience/test_retry_without_duplicate_issue_comments.py` — `stubbed`
- `tests/builders/e2e/test_resume_after_runtime_restart.py` — `stubbed`

## AC-19 Runtime Version Changes Do Not Require Core Restart

Description:

- Builders runtime can change while Stronghold core stays up

Tests:

- `tests/builders/contracts/test_version_compatibility.py` — `stubbed`
- `tests/builders/evidence/test_version_skew_compatibility.py` — `stubbed`
- `tests/builders/e2e/test_runtime_version_swap.py` — `stubbed`

## AC-20 The Full Issue-To-PR Flow Works

Description:

- the whole system takes an issue to a mergeable PR under the new architecture

Tests:

- `tests/builders/e2e/test_issue_to_pr_happy_path.py` — `stubbed`
- `tests/builders/e2e/test_spec_revision_loop.py` — `stubbed`
- `tests/builders/e2e/test_blocked_run.py` — `stubbed`
- `tests/builders/e2e/test_failed_run.py` — `stubbed`
- `tests/builders/e2e/test_resume_after_runtime_restart.py` — `stubbed`

## AC-21 PR Audit Findings Become Durable Learning Inputs

Description:

- structured audit findings must feed the learning pipeline through durable artifacts

Tests:

- `tests/builders/integration/test_audit_to_learning_handoff.py` — `future`
- `tests/builders/services/test_artifact_store.py` — `stubbed`
- `tests/builders/evidence/test_artifact_lineage.py` — `stubbed`

## AC-22 Learning Targets Are Attributed Correctly

Description:

- learning artifacts must target `mason`, `frank`, or `builders_workflow` correctly

Tests:

- `tests/builders/evidence/test_learning_target_attribution.py` — `future`

## AC-23 Future Builders Runs Load Relevant Learnings

Description:

- future Builders runs must receive relevant learnings through contracts/context loading

Tests:

- `tests/builders/integration/test_audit_to_learning_handoff.py` — `future`
- `tests/builders/runtime/test_artifact_production.py` — `stubbed`

## Exit Condition For Planning

Planning for test completeness is done when:

- no acceptance criterion lacks test coverage
- every Builders 2.0 criterion points to named files
- every named file exists

That condition is now met at the suite-planning level.
