"""Protocol conformance tests for MemoryRepo and WorkingMemoryStore.

These verify that any class claiming to satisfy the MemoryRepo or
WorkingMemoryStore protocol actually honours the contract. They run
against every registered backend (SQLite for now, Postgres later).

Acceptance criteria are documented in protocols.py alongside each protocol.
"""

from __future__ import annotations

import pytest

from turing.protocols import MemoryRepo, WorkingMemoryStore
from turing.repo import Repo
from turing.types import DURABLE_TIERS, EpisodicMemory, MemoryTier, SourceKind
from turing.working_memory import WorkingMemory


def _memory(**overrides: object) -> EpisodicMemory:
    defaults = dict(
        memory_id="m1",
        self_id="self-1",
        tier=MemoryTier.OBSERVATION,
        content="test memory",
        weight=0.3,
        source=SourceKind.I_DID,
    )
    defaults.update(overrides)
    return EpisodicMemory(**defaults)


BACKEND_FACTORIES: list[tuple[str, object]] = [
    ("sqlite_repo", lambda: Repo()),
]


@pytest.fixture(
    params=[name for name, _ in BACKEND_FACTORIES], ids=[name for name, _ in BACKEND_FACTORIES]
)
def repo(request: pytest.FixtureRequest) -> Repo:
    for name, factory in BACKEND_FACTORIES:
        if name == request.param:
            r = factory()
            yield r
            r.close()


def _find_factory(name: str):
    for n, f in BACKEND_FACTORIES:
        if n == name:
            return f


class TestMemoryRepoProtocolConformance:
    def test_repo_satisfies_protocol(self) -> None:
        assert isinstance(Repo(), MemoryRepo)

    def test_ac1_insert_get_roundtrip(self, repo: MemoryRepo) -> None:
        m = _memory()
        mid = repo.insert(m)
        assert mid == "m1"
        got = repo.get(mid)
        assert got is not None
        assert got.content == "test memory"
        assert got.tier == MemoryTier.OBSERVATION

    def test_ac1_get_nonexistent_returns_none(self, repo: MemoryRepo) -> None:
        assert repo.get("no-such-id") is None

    def test_ac2_durable_rejects_soft_delete(self, repo: MemoryRepo) -> None:
        from turing.repo import ImmutableViolation

        m = _memory(tier=MemoryTier.REGRET, weight=0.7, source=SourceKind.I_DID)
        repo.insert(m)
        with pytest.raises(ImmutableViolation):
            repo.soft_delete("m1")

    def test_ac3_superseded_by_settable_once(self, repo: MemoryRepo) -> None:
        from turing.repo import ImmutableViolation

        m1 = _memory(memory_id="m1")
        m2 = _memory(memory_id="m2", supersedes="m1")
        repo.insert(m1)
        repo.insert(m2)
        repo.set_superseded_by("m1", "m2")
        with pytest.raises(ImmutableViolation):
            repo.set_superseded_by("m1", "m3")

    def test_ac4_decay_weight_clamps_to_floor(self, repo: MemoryRepo) -> None:
        m = _memory(weight=0.3)
        repo.insert(m)
        new_w = repo.decay_weight("m1", 100.0)
        assert new_w == 0.1

    def test_ac5_find_no_filters_returns_all(self, repo: MemoryRepo) -> None:
        repo.insert(_memory(memory_id="a"))
        repo.insert(_memory(memory_id="b"))
        found = list(repo.find())
        assert len(found) == 2

    def test_ac6_close_idempotent(self) -> None:
        r = Repo()
        r.close()
        r.close()

    def test_get_head_walks_superseded_chain(self, repo: MemoryRepo) -> None:
        repo.insert(_memory(memory_id="m1"))
        repo.insert(_memory(memory_id="m2", supersedes="m1"))
        repo.set_superseded_by("m1", "m2")
        head = repo.get_head("m1")
        assert head is not None
        assert head.memory_id == "m2"

    def test_walk_lineage_oldest_first(self, repo: MemoryRepo) -> None:
        repo.insert(_memory(memory_id="m1"))
        repo.insert(_memory(memory_id="m2", supersedes="m1"))
        chain = repo.walk_lineage("m2")
        assert [m.memory_id for m in chain] == ["m1", "m2"]

    def test_count_by_tier(self, repo: MemoryRepo) -> None:
        repo.insert(_memory(memory_id="m1", tier=MemoryTier.OBSERVATION, weight=0.3))
        repo.insert(_memory(memory_id="m2", tier=MemoryTier.HYPOTHESIS, weight=0.3))
        assert repo.count_by_tier(MemoryTier.OBSERVATION) == 1
        assert repo.count_by_tier(MemoryTier.HYPOTHESIS) == 1

    def test_touch_access_updates_timestamp(self, repo: MemoryRepo) -> None:
        from datetime import UTC, datetime

        repo.insert(_memory())
        before = repo.get("m1")
        assert before is not None
        repo.touch_access("m1")
        after = repo.get("m1")
        assert after is not None
        assert after.last_accessed_at >= before.last_accessed_at

    def test_increment_contradiction_count(self, repo: MemoryRepo) -> None:
        repo.insert(_memory())
        repo.increment_contradiction_count("m1")
        m = repo.get("m1")
        assert m is not None
        assert m.contradiction_count == 1

    def test_find_filters_by_self_id(self, repo: MemoryRepo) -> None:
        repo.insert(_memory(memory_id="m1", self_id="alice"))
        repo.insert(_memory(memory_id="m2", self_id="bob"))
        found = list(repo.find(self_id="alice"))
        assert len(found) == 1
        assert found[0].self_id == "alice"

    def test_find_filters_by_tier(self, repo: MemoryRepo) -> None:
        repo.insert(_memory(memory_id="m1", tier=MemoryTier.OBSERVATION, weight=0.3))
        repo.insert(_memory(memory_id="m2", tier=MemoryTier.HYPOTHESIS, weight=0.3))
        found = list(repo.find(tier=MemoryTier.OBSERVATION))
        assert len(found) == 1


class TestWorkingMemoryProtocolConformance:
    def test_working_memory_satisfies_protocol(self) -> None:
        r = Repo()
        wm = WorkingMemory(r.conn)
        assert isinstance(wm, WorkingMemoryStore)

    def test_ac7_add_returns_entry_id(self) -> None:
        r = Repo()
        wm = WorkingMemory(r.conn)
        eid = wm.add("self-1", "hello")
        assert isinstance(eid, str)
        entries = wm.entries("self-1")
        assert len(entries) == 1
        assert entries[0].content == "hello"
        r.close()

    def test_ac8_auto_evicts_lowest_priority(self) -> None:
        r = Repo()
        wm = WorkingMemory(r.conn)
        for i in range(12):
            wm.add("self-1", f"item-{i}", priority=i / 11.0, max_entries=10)
        entries = wm.entries("self-1")
        assert len(entries) == 10
        assert entries[0].content != "item-0"
        r.close()

    def test_ac9_remove_returns_bool(self) -> None:
        r = Repo()
        wm = WorkingMemory(r.conn)
        eid = wm.add("self-1", "hello")
        removed_first = wm.remove("self-1", eid)
        assert removed_first is True
        removed_second = wm.remove("self-1", eid)
        assert removed_second is False
        r.close()

    def test_ac10_clear_returns_count(self) -> None:
        r = Repo()
        wm = WorkingMemory(r.conn)
        wm.add("self-1", "a")
        wm.add("self-1", "b")
        assert wm.clear("self-1") == 2
        assert wm.entries("self-1") == []
        r.close()
