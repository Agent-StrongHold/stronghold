# Builders 2.0 Legacy Test Inventory

## Scope

This is the stricter first-pass inventory for the architecture-sensitive parts of the current suite:

- `tests/agents/`
- `tests/api/`
- `tests/integration/`
- `tests/e2e/`

Status labels:

- `keep`
- `rewrite`
- `delete`

Where possible, rewrite targets point at the new `tests/builders/` tree.

## Agents

### Keep

- `agents/auditor/test_checks.py`
- `agents/feedback/test_extractor.py`
- `agents/feedback/test_loop.py`
- `agents/feedback/test_tracker.py`
- `agents/test_agent_handle.py`
- `agents/test_agent_store.py`
- `agents/test_ambiguous_clarification.py`
- `agents/test_arbiter_clarification.py`
- `agents/test_artificer_context_filtering.py`
- `agents/test_artificer_plan_execute.py`
- `agents/test_artificer_receives_filtered.py`
- `agents/test_artificer_strategy.py`
- `agents/test_artificer_tool_wiring.py`
- `agents/test_artificer_tools.py`
- `agents/test_base_learning.py`
- `agents/test_conduit_context_gathering.py`
- `agents/test_conduit_reflect_clarify.py`
- `agents/test_context_filter.py`
- `agents/test_coverage_agents.py`
- `agents/test_factory_coverage.py`
- `agents/test_learning_feedback.py`
- `agents/test_react_extended.py`
- `agents/test_request_analyzer.py`
- `agents/test_request_sufficiency.py`
- `agents/test_session_injection.py`
- `agents/test_session_intent_sticky.py`
- `agents/test_strategies.py`
- `agents/test_sufficiency_layers.py`
- `agents/test_task_queue.py`
- `agents/test_tool_http.py`
- `agents/test_tool_http_coverage.py`
- `agents/test_tool_http_extended.py`
- `agents/test_tool_schema_injection.py`
- `agents/test_worker.py`
- `agents/test_worker_extended.py`

Reason:

- these primarily validate generic agent runtime behavior
- they are not specific to the old embedded Builders runtime

### Rewrite

- `agents/mason/test_queue.py`
  Rewrite target:
  `tests/builders/core/` and `tests/builders/resilience/`

- `agents/mason/test_strategy.py`
  Rewrite target:
  `tests/builders/runtime/`, `tests/builders/core/`, `tests/builders/evidence/`

- `agents/test_full_pipeline.py`
  Rewrite target:
  split between generic-agent pipeline tests and `tests/builders/integration/`

- `agents/test_github_flow.py`
  Rewrite target:
  `tests/builders/integration/` and `tests/builders/e2e/`

### Keep For Now, Re-evaluate Later

- `agents/mason/test_scanner.py`

Reason:

- this appears to test a Mason support tool rather than the orchestration model
- keep until the Builder support-tool boundary is finalized

## API

### Keep

- `api/test_admin_coverage.py`
- `api/test_admin_routes.py`
- `api/test_agents_extended_coverage.py`
- `api/test_agents_routes.py`
- `api/test_auth_routes_coverage.py`
- `api/test_coverage_routes.py`
- `api/test_dashboard_coverage.py`
- `api/test_dashboard_routes.py`
- `api/test_gate_routes.py`
- `api/test_litellm_client.py`
- `api/test_marketplace_coverage.py`
- `api/test_mcp_routes_coverage.py`
- `api/test_middleware.py`
- `api/test_profile_coverage.py`
- `api/test_sessions_routes.py`
- `api/test_skills_routes.py`
- `api/test_stream_routes.py`
- `api/test_tasks_routes.py`
- `api/test_traces_routes.py`
- `api/test_webhook_routes.py`

Reason:

- these belong to Stronghold core or generic platform surfaces
- they are not inherently tied to the old embedded Builders runtime

### Rewrite

- `api/test_mason_routes.py`
  Rewrite target:
  `tests/builders/integration/`, `tests/builders/services/`, and future Builders API tests

Reason:

- current test assumes old Mason-specific embedded routes and queue wiring

## Integration

### Keep

- `integration/test_coverage_api.py`
- `integration/test_gate.py`
- `integration/test_http_lifecycle.py`
- `integration/test_prompt_management.py`
- `integration/test_real_llm.py`
- `integration/test_structured_request.py`
- `integration/test_tracing.py`
- `integration/test_warden_in_pipeline.py`

Reason:

- these validate core platform behavior that still matters after the Builders split

### Rewrite

- `integration/test_evidence_driven.py`
  Rewrite target:
  split between generic agent evidence tests and `tests/builders/evidence/`

- `integration/test_full_pipeline_e2e.py`
  Rewrite target:
  `tests/builders/e2e/` and `tests/builders/integration/`

Reason:

- these likely assume the old embedded delivery flow
- the concepts remain important, but the architecture target changes

## E2E

### Rewrite

- `e2e/test_full_stack.py`
  Rewrite target:
  keep a Stronghold full-stack test plus add Builders-specific full-stack coverage in `tests/builders/e2e/`

Reason:

- end-to-end value remains
- architecture assumptions need to change once Builders runtime becomes external

## Initial Delete Candidates

No immediate delete actions should happen yet.

Delete should only happen after replacement tests are real and passing.

The most likely eventual delete candidates are:

- old embedded Mason strategy tests after Builders runtime tests replace them
- old Mason route tests after Builders API/service tests replace them

## Summary

### Keep

Most of:

- `tests/auth/`
- `tests/security/`
- `tests/routing/`
- `tests/classification/`
- `tests/memory/`
- `tests/prompts/`
- `tests/quota/`
- `tests/sessions/`
- `tests/tools/`
- most of `tests/agents/`
- most of `tests/api/`
- much of `tests/integration/`

### Rewrite First

- `agents/mason/test_queue.py`
- `agents/mason/test_strategy.py`
- `agents/test_full_pipeline.py`
- `agents/test_github_flow.py`
- `api/test_mason_routes.py`
- `integration/test_evidence_driven.py`
- `integration/test_full_pipeline_e2e.py`
- `e2e/test_full_stack.py`

### Delete Later

- only after replacement Builders tests are implemented and passing

## Next Pass

The next pass should inventory:

- all remaining top-level directories not yet reviewed in detail
- per-file rewrite targets for any file still marked broadly
- which existing tests should be duplicated temporarily during transition
