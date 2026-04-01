# Mason Agent Rules

## MUST-ALWAYS
- Write failing tests before writing implementation code (TDD)
- Run the full quality gate (pytest, ruff check, ruff format, mypy --strict, bandit) before opening a PR
- Read ARCHITECTURE.md and CLAUDE.md before starting work on any issue
- Read existing tests and source files related to the issue before writing code
- Create exactly one PR per issue, on a dedicated branch
- Reference the issue number in the PR title or body
- Follow the existing code style, naming conventions, and project structure
- Use protocol-driven DI — import protocols, not concrete implementations
- Record learnings from failures and successful patterns
- Skip issues that are underspecified, blocked, or out of scope — with a comment explaining why
- Verify all pre-existing tests still pass after your changes
- Use fakes from tests/fakes.py instead of unittest.mock for protocol dependencies

## MUST-NEVER
- Skip or bypass any quality gate check (pytest, ruff, mypy, bandit)
- Modify files unrelated to the current issue (no drive-by refactoring)
- Bundle work from multiple issues into a single PR
- Add features, endpoints, or capabilities not requested in the issue
- Introduce hardcoded credentials, secrets, or API keys
- Modify ARCHITECTURE.md — that requires a design decision, not implementation
- Move, rename, or reorganize production source files
- Force-push or rewrite history on shared branches
- Commit .env files, credentials, or generated artifacts
- Merge your own PRs — you open them, reviewers merge them
- Use unittest.mock when a fake implementation exists in tests/fakes.py
- Import external packages (litellm, langfuse, arize) directly in business logic
