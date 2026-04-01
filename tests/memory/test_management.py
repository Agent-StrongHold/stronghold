"""Tests for user-facing memory management — view, correct, forget."""

from __future__ import annotations

import uuid

from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.memory.management import MemoryManager
from stronghold.types.memory import EpisodicMemory, MemoryScope, MemoryTier


def _make_memory(
    *,
    user_id: str = "alice",
    org_id: str = "acme",
    content: str = "test memory",
    memory_id: str = "",
    scope: MemoryScope = MemoryScope.USER,
    tier: MemoryTier = MemoryTier.LESSON,
    weight: float = 0.6,
    deleted: bool = False,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=memory_id or f"mem-{uuid.uuid4().hex[:8]}",
        tier=tier,
        content=content,
        weight=weight,
        org_id=org_id,
        user_id=user_id,
        scope=scope,
        source="test",
        deleted=deleted,
    )


class TestListMemories:
    """list_memories returns only the caller's non-deleted memories, org-scoped."""

    async def test_returns_user_memories(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        m1 = _make_memory(content="remember alpha")
        m2 = _make_memory(content="remember beta")
        await store.store(m1)
        await store.store(m2)

        result = await mgr.list_memories(user_id="alice", org_id="acme")
        assert len(result) == 2
        contents = {r["content"] for r in result}
        assert contents == {"remember alpha", "remember beta"}

    async def test_excludes_other_users(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(user_id="alice", content="alice mem"))
        await store.store(_make_memory(user_id="bob", content="bob mem"))

        result = await mgr.list_memories(user_id="alice", org_id="acme")
        assert len(result) == 1
        assert result[0]["content"] == "alice mem"

    async def test_excludes_other_orgs(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(org_id="acme", content="acme mem"))
        await store.store(_make_memory(org_id="globex", content="globex mem"))

        result = await mgr.list_memories(user_id="alice", org_id="acme")
        assert len(result) == 1
        assert result[0]["content"] == "acme mem"

    async def test_excludes_deleted(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(content="alive"))
        await store.store(_make_memory(content="gone", deleted=True))

        result = await mgr.list_memories(user_id="alice", org_id="acme")
        assert len(result) == 1
        assert result[0]["content"] == "alive"

    async def test_respects_limit(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        for i in range(5):
            await store.store(_make_memory(content=f"mem {i}"))

        result = await mgr.list_memories(user_id="alice", org_id="acme", limit=3)
        assert len(result) == 3


class TestGetMemory:
    """get_memory retrieves a single memory by ID, org-scoped."""

    async def test_returns_memory(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        m = _make_memory(memory_id="mem-123", content="found it")
        await store.store(m)

        result = await mgr.get_memory(memory_id="mem-123", org_id="acme")
        assert result is not None
        assert result["memory_id"] == "mem-123"
        assert result["content"] == "found it"

    async def test_returns_none_for_wrong_org(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(memory_id="mem-123", org_id="acme"))

        result = await mgr.get_memory(memory_id="mem-123", org_id="globex")
        assert result is None

    async def test_returns_none_for_missing(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)

        result = await mgr.get_memory(memory_id="nonexistent", org_id="acme")
        assert result is None

    async def test_returns_none_for_deleted(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(memory_id="mem-del", deleted=True))

        result = await mgr.get_memory(memory_id="mem-del", org_id="acme")
        assert result is None


class TestCorrectMemory:
    """correct_memory updates content and sets high weight."""

    async def test_updates_content(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(
            _make_memory(memory_id="mem-fix", content="old content", weight=0.5)
        )

        ok = await mgr.correct_memory(
            memory_id="mem-fix", org_id="acme", new_content="corrected content"
        )
        assert ok is True

        result = await mgr.get_memory(memory_id="mem-fix", org_id="acme")
        assert result is not None
        assert result["content"] == "corrected content"
        # Correction should set high weight (tier ceiling)
        assert result["weight"] >= 0.8

    async def test_rejects_wrong_org(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(memory_id="mem-fix", org_id="acme"))

        ok = await mgr.correct_memory(
            memory_id="mem-fix", org_id="globex", new_content="hacked"
        )
        assert ok is False


class TestForgetMemory:
    """forget_memory soft-deletes a single memory."""

    async def test_soft_deletes(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(memory_id="mem-bye", content="forget me"))

        ok = await mgr.forget_memory(memory_id="mem-bye", org_id="acme")
        assert ok is True

        result = await mgr.get_memory(memory_id="mem-bye", org_id="acme")
        assert result is None  # deleted — invisible

    async def test_rejects_wrong_org(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(memory_id="mem-bye", org_id="acme"))

        ok = await mgr.forget_memory(memory_id="mem-bye", org_id="globex")
        assert ok is False


class TestForgetByKeyword:
    """forget_by_keyword bulk-deletes memories matching a keyword."""

    async def test_deletes_matching(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(content="pizza recipe for dinner"))
        await store.store(_make_memory(content="pizza topping ideas"))
        await store.store(_make_memory(content="weather today"))

        count = await mgr.forget_by_keyword(
            user_id="alice", org_id="acme", keyword="pizza"
        )
        assert count == 2

        remaining = await mgr.list_memories(user_id="alice", org_id="acme")
        assert len(remaining) == 1
        assert remaining[0]["content"] == "weather today"

    async def test_returns_zero_for_no_match(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(content="something else"))

        count = await mgr.forget_by_keyword(
            user_id="alice", org_id="acme", keyword="nonexistent"
        )
        assert count == 0


class TestPurgeUser:
    """purge_user GDPR: delete all of a user's memories."""

    async def test_deletes_all_user_memories(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        for i in range(4):
            await store.store(_make_memory(user_id="alice", content=f"alice mem {i}"))
        await store.store(_make_memory(user_id="bob", content="bob mem"))

        count = await mgr.purge_user(user_id="alice", org_id="acme")
        assert count == 4

        alice_mems = await mgr.list_memories(user_id="alice", org_id="acme")
        assert len(alice_mems) == 0

        bob_mems = await mgr.list_memories(user_id="bob", org_id="acme")
        assert len(bob_mems) == 1

    async def test_respects_org_boundary(self) -> None:
        store = InMemoryEpisodicStore()
        mgr = MemoryManager(store)
        await store.store(_make_memory(user_id="alice", org_id="acme", content="acme"))
        await store.store(
            _make_memory(user_id="alice", org_id="globex", content="globex")
        )

        count = await mgr.purge_user(user_id="alice", org_id="acme")
        assert count == 1

        # Globex memory survives
        globex = await mgr.list_memories(user_id="alice", org_id="globex")
        assert len(globex) == 1
