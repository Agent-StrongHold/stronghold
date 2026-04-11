"""Tests for RedisSessionStore — org-scoped, TTL-filtered, trimmed."""

from __future__ import annotations

import time

import fakeredis.aioredis
import pytest

from stronghold.cache.session_store import RedisSessionStore


@pytest.fixture
async def store() -> RedisSessionStore:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    return RedisSessionStore(
        redis=redis, ttl_seconds=3600, max_messages=5, key_prefix="sess:"
    )


class TestAppendAndGet:
    @pytest.mark.asyncio
    async def test_append_then_get_roundtrips(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages(
            "acme/eng/alice:chat",
            [{"role": "user", "content": "hi"}],
        )
        history = await store.get_history("acme/eng/alice:chat")
        assert history == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_append_multiple_roles(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages(
            "acme/eng/alice:chat",
            [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
                {"role": "user", "content": "three"},
            ],
        )
        history = await store.get_history("acme/eng/alice:chat")
        assert [m["content"] for m in history] == ["one", "two", "three"]
        assert [m["role"] for m in history] == ["user", "assistant", "user"]

    @pytest.mark.asyncio
    async def test_get_missing_session_returns_empty(
        self, store: RedisSessionStore
    ) -> None:
        assert await store.get_history("acme/eng/bob:none") == []


class TestOrgScoping:
    @pytest.mark.asyncio
    async def test_bare_session_id_rejected_on_get(
        self, store: RedisSessionStore
    ) -> None:
        assert await store.get_history("no-slash-here") == []

    @pytest.mark.asyncio
    async def test_bare_session_id_rejected_on_append(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages(
            "bare-id", [{"role": "user", "content": "should not land"}]
        )
        # Nothing was written. Querying a scoped id returns empty too.
        assert await store.get_history("acme/eng/alice:bare-id") == []

    @pytest.mark.asyncio
    async def test_bare_session_id_rejected_on_delete(
        self, store: RedisSessionStore
    ) -> None:
        await store.delete_session("bare-id")  # Must not raise.


class TestFiltering:
    @pytest.mark.asyncio
    async def test_invalid_role_filtered(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages(
            "acme/eng/alice:chat",
            [
                {"role": "user", "content": "keep"},
                {"role": "system", "content": "drop"},
                {"role": "assistant", "content": "keep"},
            ],
        )
        history = await store.get_history("acme/eng/alice:chat")
        assert [m["content"] for m in history] == ["keep", "keep"]

    @pytest.mark.asyncio
    async def test_non_string_content_filtered(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages(
            "acme/eng/alice:chat",
            [
                {"role": "user", "content": "ok"},
                {"role": "user", "content": 42},  # type: ignore[dict-item]
            ],
        )
        history = await store.get_history("acme/eng/alice:chat")
        assert len(history) == 1
        assert history[0]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_message_list_is_noop(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages("acme/eng/alice:chat", [])
        assert await store.get_history("acme/eng/alice:chat") == []


class TestTrimming:
    @pytest.mark.asyncio
    async def test_trim_to_max_messages(
        self, store: RedisSessionStore
    ) -> None:
        # max_messages=5 from fixture
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
        await store.append_messages("acme/eng/alice:chat", msgs)
        history = await store.get_history("acme/eng/alice:chat")
        assert len(history) == 5
        # Most recent retained
        assert [m["content"] for m in history] == ["m5", "m6", "m7", "m8", "m9"]

    @pytest.mark.asyncio
    async def test_explicit_max_messages_on_get(
        self, store: RedisSessionStore
    ) -> None:
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        await store.append_messages("acme/eng/alice:chat", msgs)
        history = await store.get_history("acme/eng/alice:chat", max_messages=2)
        assert len(history) == 2
        assert [m["content"] for m in history] == ["m3", "m4"]


class TestPerMessageTTL:
    @pytest.mark.asyncio
    async def test_stale_messages_filtered_on_get(
        self, store: RedisSessionStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Messages older than the TTL must be filtered out on read."""
        base_t = [1000.0]

        monkeypatch.setattr(time, "time", lambda: base_t[0])
        # Write an old message at t=1000
        await store.append_messages(
            "acme/eng/alice:chat",
            [{"role": "user", "content": "ancient"}],
        )
        # Fast-forward past the TTL (3600s default)
        base_t[0] = 5000.0
        # Write a fresh one
        await store.append_messages(
            "acme/eng/alice:chat",
            [{"role": "user", "content": "fresh"}],
        )
        history = await store.get_history(
            "acme/eng/alice:chat", ttl_seconds=3600
        )
        assert [m["content"] for m in history] == ["fresh"]


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_session(
        self, store: RedisSessionStore
    ) -> None:
        await store.append_messages(
            "acme/eng/alice:chat",
            [{"role": "user", "content": "gone"}],
        )
        await store.delete_session("acme/eng/alice:chat")
        assert await store.get_history("acme/eng/alice:chat") == []
