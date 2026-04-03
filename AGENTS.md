# Repository Guidelines

## Project Structure & Module Organization
Source lives in `src/stronghold/`. Main areas include `api/` for FastAPI routes, `agents/` for agent logic, `tools/` for executable tools, `memory/` for learning and outcomes, and `security/` for auth and policy. Tests live in `tests/`, with focused suites such as `tests/builders/`, `tests/api/`, `tests/security/`, and `tests/integration/`. Long-lived agent definitions and prompts live under `agents/`, while deployment assets are in `deploy/` and docs in `docs/`.

## Build, Test, and Development Commands
Use `docker compose up -d` to start the local stack, then `curl http://localhost:8100/health` to verify it is up. Run the full test suite with `pytest tests/ -x -q --no-header`; this is also the configured pre-commit test entrypoint. For targeted work, use paths such as `pytest tests/builders/ -q` or `pytest tests/api/test_mason_routes.py -q`. Run `pre-commit run --all-files` before pushing if you touch Python code or docs that affect linting.

## Coding Style & Naming Conventions
This is a Python 3.12 codebase. Use 4-space indentation, type hints on new code, and keep imports organized for Ruff. Format with `ruff format` and lint with `ruff`. Modules and functions use `snake_case`; classes use `PascalCase`; test files use `test_*.py`, and test names should describe behavior clearly. Prefer small, explicit functions over implicit side effects.

## Testing Guidelines
Pytest is the test framework. Keep tests deterministic and isolated; use the in-memory services in `tests/builders/` where possible. New behavior should add or update tests in the nearest suite, and architecture changes should usually add evidence-based tests that prove the contract or failure mode, not just the happy path. The Builders flow expects strong coverage, so add tests for state transitions, idempotency, and restart/retry behavior when relevant.

## Commit & Pull Request Guidelines
History uses conventional commits such as `feat:` and `fix:`. Keep commit subjects short and imperative, for example `fix: workspace fallback for read-only containers`. Pull requests should summarize the behavioral change, link the issue, note test coverage, and call out any config or deployment impact. Include screenshots only when the UI changes.

## Agent-Specific Notes
Frank/Mason work is treated as workflow infrastructure, not generic agent logic. If you touch Builders code, keep the runtime stateless, persist run state outside the worker, and preserve the core-orchestrator boundary. Prefer changing contracts and tests first, then implementation.
