# Builders 2.0 Legacy Test Disposition

## Purpose

This document classifies the existing test suite during the Builders 2.0 changeover.

Every current test should end up in one of three buckets:

- `keep`
- `rewrite`
- `delete`

This is not the final per-file inventory for all tests yet.
It is the initial architectural disposition map so code movement can begin safely.

## Current Suite Shape

Current test file count:

- `227` test files under `tests/`

Largest current groups:

- `33` in `agents/`
- `27` in `security/`
- `21` in `api/`
- `13` in `memory/`
- `11` in `routing/`
- `10` in `integration/`

## Disposition Rules

### Keep

A test is `keep` if it still verifies a valid invariant in the future architecture.

Examples:

- auth rules
- security boundaries
- routing behavior for generic agents
- prompt store behavior
- quota behavior
- trace behavior
- generic GitHub/tool client behavior

### Rewrite

A test is `rewrite` if the concept still matters but the test targets the old embedded Frank/Mason design.

Examples:

- Mason queue tests that should become builder run-state tests
- Mason route tests that should become Builders API or service tests
- embedded strategy tests that should become runtime/core contract tests

### Delete

A test is `delete` if it exists only to validate the old in-process Builders architecture.

Examples:

- tests tied to modules that disappear entirely
- tests whose only purpose is the old embedded MasonStrategy workflow shape

## Directory-Level Initial Disposition

### Keep

These areas are mostly platform invariants and should largely remain:

- `auth/`
- `security/`
- `routing/`
- `classification/`
- `memory/`
- `quota/`
- `sessions/`
- `prompts/`
- `config/`
- `tracing/`
- `properties/`
- `reactor/`
- `mcp/`
- most of `tools/`

### Rewrite

These areas contain concepts that still matter, but some tests assume the old Builders architecture:

- parts of `agents/`
- parts of `api/`
- parts of `integration/`
- `container/` where it assumes Builders are in-process
- `e2e/` where it assumes the old flow

### Delete

These are the most likely delete candidates once replacement coverage exists:

- old embedded Frank/Mason workflow tests that have no value after extraction
- old route/strategy tests that only prove the in-process architecture

## Directly Impacted Tests

These are the highest-priority rewrite targets.

### Rewrite First

- `agents/mason/test_queue.py`
- `agents/mason/test_strategy.py`
- `api/test_mason_routes.py`
- `agents/test_github_flow.py`
- `integration/test_full_pipeline_e2e.py`

Why:

- they are closest to the old embedded Builders design
- they should be replaced by the new `tests/builders/` suite

### Likely Keep

- `agents/mason/test_scanner.py`

Why:

- the scanner concept may still be useful as a Builder support tool
- it is less tied to the runtime split than queue/strategy/route tests

This file still needs review, but it is not the first deletion candidate.

## Mapping Old Concepts To New Test Areas

Old embedded concept to new destination:

- Mason queue -> `tests/builders/core/`
- Mason strategy -> `tests/builders/runtime/`, `tests/builders/core/`, `tests/builders/evidence/`
- Mason routes -> `tests/builders/integration/` and future Builders API tests
- full GitHub flow -> `tests/builders/e2e/`
- restart/retry behavior -> `tests/builders/resilience/`
- issue/PR reporting -> `tests/builders/services/`

## Initial Working Rule

Until each rewritten area has real replacement coverage:

- do not delete the old test immediately
- mark it as `rewrite pending`

Deletion only happens when:

- replacement Builders 2.0 tests exist
- replacement tests are passing
- the old test proves only obsolete behavior

## Next Pass

The next pass should produce a stricter inventory:

- every file in `tests/agents/`
- every file in `tests/api/`
- every file in `tests/integration/`
- every file in `tests/e2e/`

Each file should then be marked:

- `keep`
- `rewrite -> new target path`
- `delete after replacement`
