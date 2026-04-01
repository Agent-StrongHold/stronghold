"""Tests for conversation history list and search API.

Covers:
- list_sessions: returns sessions sorted by recency, respects limit/offset, scoped to user+org
- search_sessions: finds matching content, case-insensitive, empty for no matches
- Auto-title generation from first user message
- API routes: GET /sessions (list), GET /sessions/search (search), auth enforcement
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.sessions import router
from stronghold.sessions.store import InMemorySessionStore, build_session_id
from stronghold.types.auth import AuthContext
from tests.fakes import FakeAuthProvider


# ── Helpers ───────────────────────────────────────────────────────────


ORG = "acme"
TEAM = "dev"
USER = "alice"
OTHER_USER = "bob"
OTHER_ORG = "other-corp"


def _sid(user: str = USER, name: str = "chat1", org: str = ORG) -> str:
    return build_session_id(org, TEAM, user, name)


def _auth(user: str = USER, org: str = ORG) -> AuthContext:
    return AuthContext(
        user_id=user,
        username=user,
        org_id=org,
        team_id=TEAM,
        roles=frozenset({"user"}),
    )


class _FakeAuditLog:
    """Minimal audit log stub for container."""

    async def log(self, entry: Any) -> None:
        pass

    async def get_entries(self, **kwargs: Any) -> list[Any]:
        return []


class _FakeContainer:
    """Minimal container with session store + auth."""

    def __init__(
        self,
        session_store: InMemorySessionStore,
        auth_provider: FakeAuthProvider,
    ) -> None:
        self.session_store = session_store
        self.auth_provider = auth_provider
        self.audit_log = _FakeAuditLog()


def _make_app(store: InMemorySessionStore, auth: AuthContext) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.container = _FakeContainer(store, FakeAuthProvider(auth))
    return app


# ── Unit tests: InMemorySessionStore.list_sessions ────────────────────


class TestListSessions:
    """list_sessions returns user+org-scoped sessions sorted by recency."""

    async def test_returns_sessions_sorted_by_recency(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()

        # Create two sessions with different timestamps
        sid1 = _sid(name="old-chat")
        sid2 = _sid(name="new-chat")

        await store.append_messages(sid1, [{"role": "user", "content": "first message"}])
        # Small delay to ensure different timestamps
        await store.append_messages(sid2, [{"role": "user", "content": "second message"}])

        result = await store.list_sessions(
            user_id=auth.user_id, org_id=auth.org_id, limit=20, offset=0
        )
        assert len(result) == 2
        # Most recent first
        assert result[0]["session_id"] == sid2
        assert result[1]["session_id"] == sid1

    async def test_respects_limit(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()

        for i in range(5):
            sid = _sid(name=f"chat-{i}")
            await store.append_messages(sid, [{"role": "user", "content": f"msg {i}"}])

        result = await store.list_sessions(
            user_id=auth.user_id, org_id=auth.org_id, limit=3, offset=0
        )
        assert len(result) == 3

    async def test_respects_offset(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()

        for i in range(5):
            sid = _sid(name=f"chat-{i}")
            await store.append_messages(sid, [{"role": "user", "content": f"msg {i}"}])

        all_results = await store.list_sessions(
            user_id=auth.user_id, org_id=auth.org_id, limit=20, offset=0
        )
        offset_results = await store.list_sessions(
            user_id=auth.user_id, org_id=auth.org_id, limit=20, offset=2
        )
        assert len(offset_results) == 3
        assert offset_results[0]["session_id"] == all_results[2]["session_id"]

    async def test_scoped_to_user_id(self) -> None:
        store = InMemorySessionStore()

        sid_alice = _sid(user=USER, name="chat")
        sid_bob = _sid(user=OTHER_USER, name="chat")

        await store.append_messages(sid_alice, [{"role": "user", "content": "alice msg"}])
        await store.append_messages(sid_bob, [{"role": "user", "content": "bob msg"}])

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert len(result) == 1
        assert result[0]["session_id"] == sid_alice

    async def test_scoped_to_org_id(self) -> None:
        store = InMemorySessionStore()

        sid_acme = _sid(user=USER, org=ORG, name="chat")
        sid_other = _sid(user=USER, org=OTHER_ORG, name="chat")

        await store.append_messages(sid_acme, [{"role": "user", "content": "acme msg"}])
        await store.append_messages(sid_other, [{"role": "user", "content": "other msg"}])

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert len(result) == 1
        assert result[0]["session_id"] == sid_acme

    async def test_returns_metadata_fields(self) -> None:
        store = InMemorySessionStore()

        sid = _sid(name="meta-test")
        await store.append_messages(
            sid,
            [
                {"role": "user", "content": "hello world"},
                {"role": "assistant", "content": "hi there"},
            ],
        )

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert len(result) == 1
        entry = result[0]
        assert entry["session_id"] == sid
        assert entry["message_count"] == 2
        assert "started_at" in entry
        assert "last_message_at" in entry
        assert "title" in entry

    async def test_empty_when_no_sessions(self) -> None:
        store = InMemorySessionStore()
        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert result == []


# ── Unit tests: InMemorySessionStore.search_sessions ──────────────────


class TestSearchSessions:
    """search_sessions finds matching content with case-insensitive substring match."""

    async def test_finds_matching_content(self) -> None:
        store = InMemorySessionStore()

        sid = _sid(name="search-hit")
        await store.append_messages(
            sid, [{"role": "user", "content": "How do I deploy to kubernetes?"}]
        )

        result = await store.search_sessions(
            user_id=USER, org_id=ORG, query="kubernetes", limit=20
        )
        assert len(result) == 1
        assert result[0]["session_id"] == sid

    async def test_case_insensitive(self) -> None:
        store = InMemorySessionStore()

        sid = _sid(name="case-test")
        await store.append_messages(
            sid, [{"role": "user", "content": "Configure PostgreSQL replication"}]
        )

        result = await store.search_sessions(
            user_id=USER, org_id=ORG, query="postgresql", limit=20
        )
        assert len(result) == 1

    async def test_returns_empty_for_no_matches(self) -> None:
        store = InMemorySessionStore()

        sid = _sid(name="no-match")
        await store.append_messages(
            sid, [{"role": "user", "content": "Talk about cats"}]
        )

        result = await store.search_sessions(
            user_id=USER, org_id=ORG, query="kubernetes", limit=20
        )
        assert result == []

    async def test_returns_snippet_context(self) -> None:
        store = InMemorySessionStore()

        sid = _sid(name="snippet-test")
        await store.append_messages(
            sid, [{"role": "user", "content": "Help me deploy kubernetes pods"}]
        )

        result = await store.search_sessions(
            user_id=USER, org_id=ORG, query="kubernetes", limit=20
        )
        assert len(result) == 1
        assert "snippet" in result[0]
        assert "kubernetes" in result[0]["snippet"].lower()

    async def test_scoped_to_user_and_org(self) -> None:
        store = InMemorySessionStore()

        sid_alice = _sid(user=USER, name="search-scope")
        sid_bob = _sid(user=OTHER_USER, name="search-scope")

        await store.append_messages(sid_alice, [{"role": "user", "content": "deploy kubernetes"}])
        await store.append_messages(sid_bob, [{"role": "user", "content": "deploy kubernetes"}])

        result = await store.search_sessions(
            user_id=USER, org_id=ORG, query="kubernetes", limit=20
        )
        assert len(result) == 1
        assert result[0]["session_id"] == sid_alice

    async def test_respects_limit(self) -> None:
        store = InMemorySessionStore()

        for i in range(5):
            sid = _sid(name=f"search-{i}")
            await store.append_messages(sid, [{"role": "user", "content": f"kubernetes topic {i}"}])

        result = await store.search_sessions(
            user_id=USER, org_id=ORG, query="kubernetes", limit=2
        )
        assert len(result) == 2


# ── Unit tests: Auto-title generation ──────────────────────────────


class TestAutoTitle:
    """Title auto-generated from first user message, truncated to 60 chars."""

    async def test_title_from_first_user_message(self) -> None:
        store = InMemorySessionStore()
        sid = _sid(name="title-test")

        await store.append_messages(sid, [{"role": "user", "content": "How do I configure nginx?"}])

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert len(result) == 1
        assert result[0]["title"] == "How do I configure nginx?"

    async def test_title_truncated_to_60_chars(self) -> None:
        store = InMemorySessionStore()
        sid = _sid(name="long-title")
        long_msg = "A" * 100

        await store.append_messages(sid, [{"role": "user", "content": long_msg}])

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert len(result) == 1
        assert len(result[0]["title"]) <= 63  # 60 chars + "..."

    async def test_title_not_overwritten_on_subsequent_messages(self) -> None:
        store = InMemorySessionStore()
        sid = _sid(name="title-stable")

        await store.append_messages(sid, [{"role": "user", "content": "First question"}])
        await store.append_messages(sid, [{"role": "user", "content": "Second question"}])

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert result[0]["title"] == "First question"

    async def test_assistant_message_does_not_set_title(self) -> None:
        store = InMemorySessionStore()
        sid = _sid(name="assistant-first")

        await store.append_messages(sid, [{"role": "assistant", "content": "Welcome!"}])
        await store.append_messages(sid, [{"role": "user", "content": "Thanks"}])

        result = await store.list_sessions(user_id=USER, org_id=ORG, limit=20, offset=0)
        assert result[0]["title"] == "Thanks"


# ── API route tests ───────────────────────────────────────────────────


class TestSessionListRoute:
    """GET /v1/stronghold/sessions returns user-scoped conversation list."""

    def test_returns_200_with_list(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        # Seed a session
        import asyncio

        sid = _sid(name="route-test")
        asyncio.get_event_loop().run_until_complete(
            store.append_messages(sid, [{"role": "user", "content": "hello"}])
        )

        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/sessions",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    def test_requires_authentication(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/sessions")
            assert resp.status_code == 401

    def test_respects_limit_and_offset_params(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        import asyncio

        for i in range(5):
            sid = _sid(name=f"route-{i}")
            asyncio.get_event_loop().run_until_complete(
                store.append_messages(sid, [{"role": "user", "content": f"msg {i}"}])
            )

        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/sessions?limit=2&offset=1",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 2


class TestSessionSearchRoute:
    """GET /v1/stronghold/sessions/search?q=... returns matching conversations."""

    def test_returns_results_for_matching_query(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        import asyncio

        sid = _sid(name="search-route")
        asyncio.get_event_loop().run_until_complete(
            store.append_messages(sid, [{"role": "user", "content": "deploy kubernetes pods"}])
        )

        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/sessions/search?q=kubernetes",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) >= 1

    def test_requires_authentication(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/sessions/search?q=test")
            assert resp.status_code == 401

    def test_returns_empty_for_no_matches(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/sessions/search?q=nonexistent",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data == []

    def test_requires_query_param(self) -> None:
        store = InMemorySessionStore()
        auth = _auth()
        app = _make_app(store, auth)

        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/sessions/search",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 422  # FastAPI validation error
