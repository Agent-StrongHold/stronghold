"""Tests for request context propagation via contextvars.

Validates:
- RequestContext dataclass construction and defaults
- ContextVar-based get/set/reset lifecycle
- Middleware creates context from request headers and auth
- Context isolation across concurrent tasks
- Token-based reset restores previous context
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from starlette.testclient import TestClient

from stronghold.context.request import (
    RequestContext,
    get_request_context,
    request_context_middleware,
    set_request_context,
)


class TestRequestContextDataclass:
    """RequestContext construction and field validation."""

    def test_defaults_generate_uuid_and_timestamp(self) -> None:
        ctx = RequestContext(user_id="u1", org_id="org1")
        # request_id should be a valid UUID
        UUID(str(ctx.request_id))
        assert ctx.user_id == "u1"
        assert ctx.org_id == "org1"
        assert ctx.session_id == ""
        assert ctx.trace_id == ""
        assert ctx.execution_mode == "best_effort"
        assert ctx.model_override is None
        assert isinstance(ctx.started_at, datetime)
        # started_at should be timezone-aware (UTC)
        assert ctx.started_at.tzinfo is not None

    def test_all_fields_set(self) -> None:
        ts = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        ctx = RequestContext(
            request_id="custom-id",
            user_id="user-42",
            org_id="org-7",
            session_id="sess-99",
            trace_id="trace-abc",
            started_at=ts,
            execution_mode="strict",
            model_override="gpt-4o",
        )
        assert ctx.request_id == "custom-id"
        assert ctx.user_id == "user-42"
        assert ctx.org_id == "org-7"
        assert ctx.session_id == "sess-99"
        assert ctx.trace_id == "trace-abc"
        assert ctx.started_at == ts
        assert ctx.execution_mode == "strict"
        assert ctx.model_override == "gpt-4o"

    def test_request_id_unique_per_instance(self) -> None:
        ctx1 = RequestContext(user_id="u", org_id="o")
        ctx2 = RequestContext(user_id="u", org_id="o")
        assert ctx1.request_id != ctx2.request_id


class TestContextVarLifecycle:
    """get/set/reset via contextvars."""

    def test_get_returns_none_when_unset(self) -> None:
        # In a fresh context, should be None
        assert get_request_context() is None

    def test_set_and_get_round_trip(self) -> None:
        ctx = RequestContext(user_id="u1", org_id="org1")
        token = set_request_context(ctx)
        try:
            assert get_request_context() is ctx
        finally:
            # Reset so we don't leak into other tests
            from stronghold.context.request import _request_context_var

            _request_context_var.reset(token)

    def test_token_reset_restores_previous(self) -> None:
        ctx_old = RequestContext(user_id="old", org_id="org-old")
        token_old = set_request_context(ctx_old)

        ctx_new = RequestContext(user_id="new", org_id="org-new")
        token_new = set_request_context(ctx_new)
        assert get_request_context() is ctx_new

        from stronghold.context.request import _request_context_var

        _request_context_var.reset(token_new)
        assert get_request_context() is ctx_old

        _request_context_var.reset(token_old)

    async def test_isolation_across_async_tasks(self) -> None:
        """Each asyncio task gets its own copy of the context var."""
        results: dict[str, str | None] = {}

        async def task_a() -> None:
            ctx = RequestContext(user_id="task-a", org_id="org-a")
            set_request_context(ctx)
            await asyncio.sleep(0.01)
            found = get_request_context()
            results["a"] = found.user_id if found else None

        async def task_b() -> None:
            ctx = RequestContext(user_id="task-b", org_id="org-b")
            set_request_context(ctx)
            await asyncio.sleep(0.01)
            found = get_request_context()
            results["b"] = found.user_id if found else None

        await asyncio.gather(task_a(), task_b())

        assert results["a"] == "task-a"
        assert results["b"] == "task-b"


class TestRequestContextMiddleware:
    """Middleware creates RequestContext from request headers/auth."""

    def _make_app(self) -> TestClient:
        """Build a minimal FastAPI app with the middleware and a probe route."""
        from fastapi import FastAPI, Request
        from fastapi.responses import JSONResponse

        app = FastAPI()

        @app.middleware("http")
        async def ctx_mw(request: Request, call_next: object) -> object:  # type: ignore[type-arg]
            return await request_context_middleware(request, call_next)  # type: ignore[arg-type]

        @app.get("/probe")
        async def probe() -> JSONResponse:
            ctx = get_request_context()
            if ctx is None:
                return JSONResponse({"ctx": None})
            return JSONResponse(
                {
                    "request_id": ctx.request_id,
                    "user_id": ctx.user_id,
                    "org_id": ctx.org_id,
                    "session_id": ctx.session_id,
                    "trace_id": ctx.trace_id,
                    "execution_mode": ctx.execution_mode,
                    "model_override": ctx.model_override or "",
                }
            )

        return TestClient(app)

    def test_middleware_sets_context_from_headers(self) -> None:
        client = self._make_app()
        resp = client.get(
            "/probe",
            headers={
                "X-Request-ID": "req-123",
                "X-User-ID": "user-abc",
                "X-Org-ID": "org-xyz",
                "X-Session-ID": "sess-456",
                "X-Trace-ID": "trace-789",
                "X-Execution-Mode": "strict",
                "X-Model-Override": "gpt-4o",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == "req-123"
        assert data["user_id"] == "user-abc"
        assert data["org_id"] == "org-xyz"
        assert data["session_id"] == "sess-456"
        assert data["trace_id"] == "trace-789"
        assert data["execution_mode"] == "strict"
        assert data["model_override"] == "gpt-4o"

    def test_middleware_defaults_when_no_headers(self) -> None:
        client = self._make_app()
        resp = client.get("/probe")
        assert resp.status_code == 200
        data = resp.json()
        # request_id should be a valid UUID even without X-Request-ID header
        UUID(data["request_id"])
        assert data["user_id"] == ""
        assert data["org_id"] == ""
        assert data["session_id"] == ""
        assert data["execution_mode"] == "best_effort"

    def test_middleware_resets_context_after_request(self) -> None:
        client = self._make_app()
        # Make a request that sets context
        client.get("/probe", headers={"X-User-ID": "user-leak"})
        # After the request, context should be cleared
        assert get_request_context() is None

    def test_middleware_partial_headers(self) -> None:
        client = self._make_app()
        resp = client.get(
            "/probe",
            headers={
                "X-User-ID": "just-user",
                "X-Org-ID": "just-org",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "just-user"
        assert data["org_id"] == "just-org"
        assert data["session_id"] == ""
        assert data["trace_id"] == ""
        assert data["model_override"] == ""

    def test_middleware_generates_request_id_when_missing(self) -> None:
        """When no X-Request-ID header, middleware auto-generates a UUID."""
        client = self._make_app()
        resp1 = client.get("/probe")
        resp2 = client.get("/probe")
        id1 = resp1.json()["request_id"]
        id2 = resp2.json()["request_id"]
        # Both should be valid UUIDs
        UUID(id1)
        UUID(id2)
        # And unique
        assert id1 != id2
