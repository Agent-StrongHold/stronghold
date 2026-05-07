"""Tests for runtime/working_memory_maintenance.py."""

from __future__ import annotations

from typing import Any

from turing.motivation import ACTION_CADENCE_TICKS, BacklogItem, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.runtime.providers.base import FreeTierWindow
from turing.runtime.working_memory_maintenance import (
    WMUpdate,
    WorkingMemoryMaintenance,
)
from turing.working_memory import WorkingMemory


class _CannedProvider:
    name = "canned"

    def __init__(self, reply: str) -> None:
        self._reply = reply

    def complete(self, prompt: str, *, max_tokens: int = 512) -> str:
        return self._reply

    def embed(self, text: str) -> list[float]:
        return [0.0]

    def quota_window(self) -> FreeTierWindow | None:
        return None


def test_maintenance_adds_entries_on_dispatch(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    wm = WorkingMemory(repo.conn)
    provider = _CannedProvider(
        reply='{"add": [{"content": "focus on routing code review",'
              ' "priority": 0.8}], "remove": []}'
    )
    wmm = WorkingMemoryMaintenance(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        working_memory=wm,
        provider=provider,
        self_id=self_id,
        poll_ticks=1,
    )

    # Tick once to submit; action sweep to dispatch.
    reactor.tick(1)
    reactor.tick(ACTION_CADENCE_TICKS)

    entries = wm.entries(self_id)
    assert entries
    assert entries[0].content == "focus on routing code review"
    assert entries[0].priority == 0.8


def test_maintenance_removes_entries_by_id(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    wm = WorkingMemory(repo.conn)
    eid = wm.add(self_id, "to go", priority=0.5)

    provider = _CannedProvider(
        reply='{"add": [], "remove": ["%s"]}' % eid
    )
    WorkingMemoryMaintenance(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        working_memory=wm,
        provider=provider,
        self_id=self_id,
        poll_ticks=1,
    )

    reactor.tick(1)
    reactor.tick(ACTION_CADENCE_TICKS)

    assert wm.entries(self_id) == []


def test_invalid_json_is_no_op(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    wm = WorkingMemory(repo.conn)
    wm.add(self_id, "keep me")

    provider = _CannedProvider(reply="nonsense not json")
    WorkingMemoryMaintenance(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        working_memory=wm,
        provider=provider,
        self_id=self_id,
        poll_ticks=1,
    )

    reactor.tick(1)
    reactor.tick(ACTION_CADENCE_TICKS)

    assert len(wm.entries(self_id)) == 1


def test_priority_clamped(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    wm = WorkingMemory(repo.conn)

    provider = _CannedProvider(
        reply='{"add": [{"content": "clamp me", "priority": 5.0}], "remove": []}'
    )
    WorkingMemoryMaintenance(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        working_memory=wm,
        provider=provider,
        self_id=self_id,
        poll_ticks=1,
    )

    reactor.tick(1)
    reactor.tick(ACTION_CADENCE_TICKS)

    entries = wm.entries(self_id)
    assert entries[0].priority == 1.0
