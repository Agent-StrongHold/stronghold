# Codebase Onboarding — Read Before Writing Any Code

This document contains everything you need to write working code for the Stronghold project.
Follow these patterns exactly. Do not guess at import paths or test patterns.

---

## App Factory

The app is created via:

```python
from stronghold.api.app import create_app
app = create_app()
```

**There is no `stronghold.main` module. Do not import from it.**

Under pytest (`PYTEST_CURRENT_TEST` env var is set automatically), `create_app()` skips
the production lifespan and uses a middleware that lazy-creates an in-memory Container on
the first request. This means:

- No database connection (no asyncpg, no PostgreSQL)
- No Redis connection
- No external LLM calls
- All stores are in-memory

You do NOT need to set up database connections in tests.

## Route Paths in Tests vs Production

**CRITICAL:** In tests, you create a bare FastAPI app and include the router directly:

```python
app = FastAPI()
app.include_router(status_router)  # No prefix!
```

This means routes are mounted at their **bare paths** — e.g., `/health`, `/version`.
In production, `create_app()` may mount routers with prefixes, but **in tests the
paths match the router definition exactly**.

So if the router defines `@router.get("/version")`, the test calls `client.get("/version")`.
Do NOT use the production path like `/v1/stronghold/version` in tests unless the router
itself defines that full path.

**Rule:** Look at what the router defines, test that path. Not the production URL.

---

## Test Pattern

Every test file in this repo follows this pattern. Copy it exactly.

```python
"""Tests for <feature>."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the router you're testing
from stronghold.api.routes.status import router as status_router

# Import the test container factory — DO NOT construct Container manually
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(status_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


class TestVersionEndpoint:
    def test_returns_200(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Use bare router path — NOT /v1/stronghold/version
            # Tests mount the router directly without prefix
            resp = client.get("/version")
            assert resp.status_code == 200

    def test_response_has_version_field(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/version").json()
            assert "version" in data

    def test_response_has_python_version(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/version").json()
            assert "python_version" in data

    def test_service_field_is_stronghold(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            data = client.get("/version").json()
            assert data["service"] == "stronghold"
```

**CRITICAL:** Use `make_test_container()` from `tests.fakes`. Do NOT construct
`Container(...)` manually — it has 12+ required arguments that change between versions.
The factory handles all of them.

---

## Available Fakes (use these, NOT unittest.mock)

All fakes are in `tests/fakes.py`:

| Class | Protocol | Key Methods |
|-------|----------|-------------|
| `FakeLLMClient` | LLMClient | `.set_simple_response(text)`, `.set_responses([...])`, `.calls` |
| `FakePromptManager` | PromptManager | `.upsert(name, content)`, `.get(name)`, `.seed(dict)` |
| `NoopTracingBackend` | TracingBackend | `.create_trace()` → NoopTrace |
| `FakeQuotaTracker` | QuotaTracker | `.usage_pct`, `.record_usage()` |
| `FakeRateLimiter` | RateLimiter | `.check()`, `.record()` |
| `FakeAuthProvider` | AuthProvider | Returns configurable AuthContext |
| `FakeViolationStore` | ViolationStore | RLHF feedback tracking |

---

## Valid Import Paths

These modules exist. Import from these paths only:

```
stronghold.api.app                    # create_app()
stronghold.api.routes.status          # health, reactor status endpoints
stronghold.api.routes.agents          # /v1/stronghold/request, /agents
stronghold.api.routes.chat            # /v1/chat/completions
stronghold.api.routes.gate_endpoint   # /v1/stronghold/gate
stronghold.agents.base                # Agent class
stronghold.agents.context_builder     # ContextBuilder
stronghold.agents.intents             # IntentRegistry
stronghold.agents.strategies.direct   # DirectStrategy
stronghold.agents.strategies.react    # ReactStrategy
stronghold.classifier.engine          # ClassifierEngine
stronghold.container                  # Container dataclass
stronghold.memory.learnings.store     # InMemoryLearningStore
stronghold.memory.learnings.extractor # ToolCorrectionExtractor
stronghold.memory.outcomes            # InMemoryOutcomeStore
stronghold.prompts.store              # InMemoryPromptManager
stronghold.quota.tracker              # InMemoryQuotaTracker
stronghold.router.selector            # RouterEngine
stronghold.security.auth_static       # StaticKeyAuthProvider
stronghold.security.gate              # Gate
stronghold.security.sentinel.audit    # InMemoryAuditLog
stronghold.security.sentinel.policy   # Sentinel
stronghold.security.warden.detector   # Warden
stronghold.sessions.store             # InMemorySessionStore
stronghold.tools.executor             # ToolDispatcher
stronghold.tools.registry             # InMemoryToolRegistry
stronghold.tracing.noop               # NoopTracingBackend
stronghold.types.agent                # AgentIdentity
stronghold.types.auth                 # AuthContext, PermissionTable
stronghold.types.config               # StrongholdConfig, TaskTypeConfig
tests.fakes                           # FakeLLMClient, etc.
```

**These do NOT exist — never import from them:**
- `stronghold.main`
- `stronghold.app`
- `stronghold.server`
- `stronghold.routes`

---

## Pytest Config

- `asyncio_mode = "auto"` — async test functions work without `@pytest.mark.asyncio`
- Auth header: `{"Authorization": "Bearer sk-test"}` (matches `router_api_key` in config)
- Line length: 100 (ruff)
- Target: Python 3.12+
- No `unittest.mock` — use `tests/fakes.py` classes instead

---

## Testing Rules (from CLAUDE.md)

1. Real integration tests, not mocks. Import and instantiate real classes.
   Only mock external HTTP calls. Use fakes from `tests/fakes.py`.
2. Never modify production code when writing tests.
3. Never move or rename production files.
4. Run the full test suite after each change.
5. Verify claimed fixes — after saying "removed X", grep to confirm.

---

## Build Rules (from CLAUDE.md)

1. No Code Without Tests (TDD) — failing test stubs first, then implementation.
2. Every Change Must Pass — pytest, ruff check, ruff format, mypy --strict, bandit -ll.
3. No Hardcoded Secrets — defaults must be example values (`sk-example-xxx`).
4. No Direct External Imports — import the protocol; the DI container wires the implementation.
5. Every Protocol Needs a Noop/Fake — test fakes in `tests/fakes.py`.
