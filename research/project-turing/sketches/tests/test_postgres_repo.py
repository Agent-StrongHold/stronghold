from __future__ import annotations

import os

import pytest

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _pg_available() -> bool:
    if not DATABASE_URL:
        return False
    try:
        import asyncpg
    except ImportError:
        return False
    try:
        import asyncio

        async def _ping() -> None:
            conn = await asyncpg.connect(DATABASE_URL, timeout=2)
            await conn.close()

        asyncio.run(_ping())
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(
        not _pg_available(),
        reason="DATABASE_URL not set or PostgreSQL not reachable",
    ),
    pytest.mark.asyncio,
]


def _memory(**overrides: object) -> EpisodicMemory:
    from turing.types import EpisodicMemory, MemoryTier, SourceKind

    defaults: dict[str, object] = dict(
        memory_id="m1",
        self_id="self-1",
        tier=MemoryTier.OBSERVATION,
        content="test memory",
        weight=0.3,
        source=SourceKind.I_DID,
    )
    defaults.update(overrides)
    return EpisodicMemory(**defaults)


@pytest.fixture
async def repo():
    from turing.postgres_repo import PostgresRepo

    r = PostgresRepo(DATABASE_URL)
    pool = await r._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS episodic_memory, durable_memory CASCADE")
    await r.create_tables()
    yield r
    try:
        pool = await r._get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS episodic_memory, durable_memory CASCADE")
    except Exception:
        pass
    await r.close()


from turing.types import EpisodicMemory, MemoryTier, SourceKind


class TestPostgresRepoProtocolConformance:
    async def test_ac1_insert_get_roundtrip(self, repo) -> None:
        m = _memory()
        mid = await repo.insert(m)
        assert mid == "m1"
        got = await repo.get(mid)
        assert got is not None
        assert got.content == "test memory"
        assert got.tier == MemoryTier.OBSERVATION

    async def test_ac1_get_nonexistent_returns_none(self, repo) -> None:
        assert await repo.get("no-such-id") is None

    async def test_ac2_durable_rejects_soft_delete(self, repo) -> None:
        from turing.protocols import ImmutableViolation

        m = _memory(tier=MemoryTier.REGRET, weight=0.7, source=SourceKind.I_DID)
        await repo.insert(m)
        with pytest.raises(ImmutableViolation):
            await repo.soft_delete("m1")

    async def test_ac3_superseded_by_settable_once(self, repo) -> None:
        from turing.protocols import ImmutableViolation

        m1 = _memory(memory_id="m1")
        m2 = _memory(memory_id="m2", supersedes="m1")
        await repo.insert(m1)
        await repo.insert(m2)
        await repo.set_superseded_by("m1", "m2")
        with pytest.raises(ImmutableViolation):
            await repo.set_superseded_by("m1", "m3")

    async def test_ac4_decay_weight_clamps_to_floor(self, repo) -> None:
        m = _memory(weight=0.3)
        await repo.insert(m)
        new_w = await repo.decay_weight("m1", 100.0)
        assert new_w == 0.1

    async def test_ac5_find_no_filters_returns_all(self, repo) -> None:
        await repo.insert(_memory(memory_id="a"))
        await repo.insert(_memory(memory_id="b"))
        found = await repo.find()
        assert len(found) == 2

    async def test_ac6_close_idempotent(self) -> None:
        from turing.postgres_repo import PostgresRepo

        r = PostgresRepo(DATABASE_URL)
        pool = await r._get_pool()
        await r.close()
        await r.close()

    async def test_get_head_walks_superseded_chain(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1"))
        await repo.insert(_memory(memory_id="m2", supersedes="m1"))
        await repo.set_superseded_by("m1", "m2")
        head = await repo.get_head("m1")
        assert head is not None
        assert head.memory_id == "m2"

    async def test_walk_lineage_oldest_first(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1"))
        await repo.insert(_memory(memory_id="m2", supersedes="m1"))
        chain = await repo.walk_lineage("m2")
        assert [m.memory_id for m in chain] == ["m1", "m2"]

    async def test_count_by_tier(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1", tier=MemoryTier.OBSERVATION, weight=0.3))
        await repo.insert(_memory(memory_id="m2", tier=MemoryTier.HYPOTHESIS, weight=0.3))
        assert await repo.count_by_tier(MemoryTier.OBSERVATION) == 1
        assert await repo.count_by_tier(MemoryTier.HYPOTHESIS) == 1

    async def test_touch_access_updates_timestamp(self, repo) -> None:
        from datetime import UTC, datetime

        await repo.insert(_memory())
        before = await repo.get("m1")
        assert before is not None
        await repo.touch_access("m1")
        after = await repo.get("m1")
        assert after is not None
        assert after.last_accessed_at >= before.last_accessed_at

    async def test_increment_contradiction_count(self, repo) -> None:
        await repo.insert(_memory())
        await repo.increment_contradiction_count("m1")
        m = await repo.get("m1")
        assert m is not None
        assert m.contradiction_count == 1

    async def test_find_filters_by_self_id(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1", self_id="alice"))
        await repo.insert(_memory(memory_id="m2", self_id="bob"))
        found = await repo.find(self_id="alice")
        assert len(found) == 1
        assert found[0].self_id == "alice"

    async def test_find_filters_by_tier(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1", tier=MemoryTier.OBSERVATION, weight=0.3))
        await repo.insert(_memory(memory_id="m2", tier=MemoryTier.HYPOTHESIS, weight=0.3))
        found = await repo.find(tier=MemoryTier.OBSERVATION)
        assert len(found) == 1

    async def test_find_excludes_deleted_by_default(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1"))
        await repo.soft_delete("m1")
        found = await repo.find()
        assert len(found) == 0

    async def test_find_include_deleted(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1"))
        await repo.soft_delete("m1")
        found = await repo.find(include_deleted=True)
        assert len(found) == 1

    async def test_find_excludes_superseded_when_flag_set(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1"))
        await repo.insert(_memory(memory_id="m2", supersedes="m1"))
        await repo.set_superseded_by("m1", "m2")
        found = await repo.find(include_superseded=False)
        assert len(found) == 1
        assert found[0].memory_id == "m2"

    async def test_insert_durable_memory(self, repo) -> None:
        m = _memory(
            memory_id="d1",
            tier=MemoryTier.REGRET,
            weight=0.7,
            source=SourceKind.I_DID,
        )
        mid = await repo.insert(m)
        assert mid == "d1"
        got = await repo.get("d1")
        assert got is not None
        assert got.tier == MemoryTier.REGRET
        assert got.immutable is True

    async def test_soft_delete_non_durable(self, repo) -> None:
        await repo.insert(_memory(memory_id="m1"))
        m = await repo.get("m1")
        assert m is not None
        assert m.deleted is False
        await repo.soft_delete("m1")
        assert await repo.get("m1") is None

    async def test_decay_weight_durable_within_bounds(self, repo) -> None:
        m = _memory(
            memory_id="d1",
            tier=MemoryTier.REGRET,
            weight=0.8,
            source=SourceKind.I_DID,
        )
        await repo.insert(m)
        new_w = await repo.decay_weight("d1", 0.1)
        assert new_w == 0.7

    async def test_context_preserved_roundtrip(self, repo) -> None:
        m = _memory(memory_id="m1", context={"key": "value", "nested": {"a": 1}})
        await repo.insert(m)
        got = await repo.get("m1")
        assert got is not None
        assert got.context == {"key": "value", "nested": {"a": 1}}

    async def test_set_superseded_by_raises_for_unknown(self, repo) -> None:
        from turing.protocols import RepoError

        with pytest.raises(RepoError):
            await repo.set_superseded_by("nonexistent", "other")

    async def test_soft_delete_raises_for_unknown(self, repo) -> None:
        from turing.protocols import RepoError

        with pytest.raises(RepoError):
            await repo.soft_delete("nonexistent")
