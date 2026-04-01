"""Tests for session-level TTL enforcement in InMemorySessionStore.

Covers: _created_at tracking, cleanup_expired bulk removal,
get_history returning empty for expired sessions, creation time
recorded on first append.
"""

from __future__ import annotations

import time

from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.session import SessionConfig


class TestCreationTimeTracking:
    """_created_at is recorded on first append only."""

    async def test_first_append_records_creation_time(self) -> None:
        store = InMemorySessionStore()
        before = time.time()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        after = time.time()

        assert "s1" in store._created_at
        assert before <= store._created_at["s1"] <= after

    async def test_second_append_does_not_update_creation_time(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "first"}])
        first_ts = store._created_at["s1"]

        # Small delay to ensure time difference
        await store.append_messages("s1", [{"role": "user", "content": "second"}])
        assert store._created_at["s1"] == first_ts

    async def test_creation_time_not_set_for_unknown_session(self) -> None:
        store = InMemorySessionStore()
        assert "nonexistent" not in store._created_at

    async def test_delete_clears_creation_time(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        assert "s1" in store._created_at

        await store.delete_session("s1")
        assert "s1" not in store._created_at

    async def test_reuse_after_delete_gets_new_creation_time(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        old_ts = store._created_at["s1"]

        await store.delete_session("s1")

        await store.append_messages("s1", [{"role": "user", "content": "new"}])
        assert store._created_at["s1"] >= old_ts


class TestGetHistoryExpiredSession:
    """get_history returns empty list for sessions older than TTL."""

    async def test_expired_session_returns_empty(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])

        # Age the session creation time
        store._created_at["s1"] = time.time() - 100_000

        history = await store.get_history("s1", ttl_seconds=86400)
        assert history == []

    async def test_non_expired_session_returns_messages(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])

        # Session was just created, should not be expired
        history = await store.get_history("s1", ttl_seconds=86400)
        assert len(history) == 1
        assert history[0]["content"] == "hello"

    async def test_expired_session_with_custom_ttl(self) -> None:
        config = SessionConfig(ttl_seconds=10)
        store = InMemorySessionStore(config=config)
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])

        # Age the session creation by 20 seconds (> 10s TTL)
        store._created_at["s1"] = time.time() - 20

        history = await store.get_history("s1")
        assert history == []

    async def test_session_just_within_ttl_returns_messages(self) -> None:
        config = SessionConfig(ttl_seconds=100)
        store = InMemorySessionStore(config=config)
        await store.append_messages("s1", [{"role": "user", "content": "recent"}])

        # Age to 50 seconds ago (within 100s TTL)
        store._created_at["s1"] = time.time() - 50

        history = await store.get_history("s1")
        assert len(history) == 1


class TestCleanupExpired:
    """cleanup_expired removes old sessions and returns count."""

    async def test_cleanup_removes_expired_sessions(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("old", [{"role": "user", "content": "old msg"}])
        await store.append_messages("new", [{"role": "user", "content": "new msg"}])

        # Age only the "old" session
        store._created_at["old"] = time.time() - 100_000

        removed = await store.cleanup_expired(ttl_seconds=86400.0)
        assert removed == 1

        # Old session fully gone
        assert "old" not in store._sessions
        assert "old" not in store._created_at
        assert "old" not in store._next_seq

        # New session preserved
        history = await store.get_history("new")
        assert len(history) == 1

    async def test_cleanup_returns_zero_when_nothing_expired(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "fresh"}])

        removed = await store.cleanup_expired(ttl_seconds=86400.0)
        assert removed == 0

    async def test_cleanup_default_ttl(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])

        # Age past the default 86400s
        store._created_at["s1"] = time.time() - 90_000

        removed = await store.cleanup_expired()
        assert removed == 1

    async def test_cleanup_removes_all_expired(self) -> None:
        store = InMemorySessionStore()
        for i in range(5):
            await store.append_messages(f"old-{i}", [{"role": "user", "content": f"msg {i}"}])
            store._created_at[f"old-{i}"] = time.time() - 200_000

        for i in range(3):
            await store.append_messages(f"new-{i}", [{"role": "user", "content": f"msg {i}"}])

        removed = await store.cleanup_expired(ttl_seconds=86400.0)
        assert removed == 5

        # All old sessions gone, all new sessions preserved
        for i in range(5):
            assert f"old-{i}" not in store._sessions
        for i in range(3):
            h = await store.get_history(f"new-{i}")
            assert len(h) == 1

    async def test_cleanup_on_empty_store(self) -> None:
        store = InMemorySessionStore()
        removed = await store.cleanup_expired(ttl_seconds=86400.0)
        assert removed == 0

    async def test_cleanup_custom_short_ttl(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])

        # Age by 5 seconds
        store._created_at["s1"] = time.time() - 5

        # With 1-second TTL, session should be expired
        removed = await store.cleanup_expired(ttl_seconds=1.0)
        assert removed == 1

        # Create a fresh one
        await store.append_messages("s2", [{"role": "user", "content": "hello"}])
        store._created_at["s2"] = time.time() - 5
        # With 10-second TTL, should still be valid
        removed = await store.cleanup_expired(ttl_seconds=10.0)
        assert removed == 0
