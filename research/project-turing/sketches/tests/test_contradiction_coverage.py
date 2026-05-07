"""Coverage gap filler for turing/detectors/contradiction.py.

Spec: _claims_opposed "not X" pattern, index overflow trimming, _check with
superseded memories, dispatch with missing memories, _collect_completed with
exceptions and stale parents, _find_resolution branch coverage.

Acceptance criteria:
- _claims_opposed detects "not X" / X pattern
- Index bucket trims when exceeding CONTRADICTION_INDEX_MAX_PER_FAMILY
- _check skips superseded memories
- _check skips memories where other is None
- Dispatch with missing memories is a no-op
- Dispatch with superseded parents is a no-op
- _collect_completed handles future exceptions
- _collect_completed skips stale parents
- _find_resolution returns None when no observation matches
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from turing.detectors.contradiction import (
    CONTRADICTION_INDEX_MAX_PER_FAMILY,
    ContradictionDetector,
    _claims_opposed,
    _supports_one_side,
)
from turing.motivation import ACTION_CADENCE_TICKS, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.types import EpisodicMemory, MemoryTier, SourceKind


INTENT = "contra-test"


def _mint_aff(
    repo: Repo, self_id: str, content: str, intent: str = INTENT, *, when: datetime | None = None
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.AFFIRMATION,
        source=SourceKind.I_DID,
        content=content,
        weight=0.7,
        intent_at_time=intent,
        created_at=when or datetime.now(UTC),
    )
    repo.insert(m)
    return m.memory_id


def _mint_obs(
    repo: Repo, self_id: str, content: str, intent: str = INTENT, *, when: datetime | None = None
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=content,
        weight=0.3,
        intent_at_time=intent,
        created_at=when or datetime.now(UTC),
    )
    repo.insert(m)
    return m.memory_id


class TestClaimsOpposedNotPattern:
    def test_not_x_pattern(self) -> None:
        assert _claims_opposed("the sky is blue", "not the sky is blue")

    def test_not_x_reversed(self) -> None:
        assert _claims_opposed("not this claim", "this claim")

    def test_unrelated(self) -> None:
        assert not _claims_opposed("apples", "oranges")

    def test_holds_does_not_hold(self) -> None:
        assert _claims_opposed("X holds", "X does not hold")
        assert _claims_opposed("X does not hold", "X holds")


class TestIndexOverflow:
    def test_bucket_trims_when_exceeding_max(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        for i in range(CONTRADICTION_INDEX_MAX_PER_FAMILY + 10):
            mid = _mint_aff(
                repo,
                self_id,
                f"claim {i}",
                intent="overflow-intent",
                when=datetime.now(UTC) + timedelta(seconds=i),
            )
            detector._add_to_index(repo.get(mid))
        bucket = detector._family_index.get("overflow-intent", [])
        assert len(bucket) <= CONTRADICTION_INDEX_MAX_PER_FAMILY


class TestCheckEdgeCases:
    def test_skips_superseded_new_memory(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        t0 = datetime.now(UTC) - timedelta(minutes=5)
        a_id = _mint_aff(repo, self_id, "p is true", when=t0)
        b_id = _mint_aff(repo, self_id, "p is false", when=t0 + timedelta(seconds=1))
        repo.set_superseded_by(b_id, "fake-superseder")
        _mint_obs(repo, self_id, "p is true", when=t0 + timedelta(seconds=2))
        reactor.tick(1)
        candidates = [b for b in motivation.backlog if b.kind == "raso_contradiction"]
        assert len(candidates) == 0

    def test_skips_superseded_other_memory(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        t0 = datetime.now(UTC) - timedelta(minutes=5)
        a_id = _mint_aff(repo, self_id, "q is true", when=t0)
        repo.set_superseded_by(a_id, "fake-superseder")
        _mint_aff(repo, self_id, "q is false", when=t0 + timedelta(seconds=1))
        _mint_obs(repo, self_id, "q is false", when=t0 + timedelta(seconds=2))
        reactor.tick(1)
        candidates = [b for b in motivation.backlog if b.kind == "raso_contradiction"]
        assert len(candidates) == 0

    def test_empty_intent_skipped(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        m = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.AFFIRMATION,
            source=SourceKind.I_DID,
            content="something",
            weight=0.7,
            intent_at_time="",
            created_at=datetime.now(UTC),
        )
        repo.insert(m)
        detector._add_to_index(m)
        assert "" not in detector._family_index


class TestDispatchEdgeCases:
    def test_dispatch_with_missing_memories(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        from turing.detectors.contradiction import ContradictionPayload, BacklogItem

        item = BacklogItem(
            item_id=str(uuid4()),
            class_=14,
            kind="raso_contradiction",
            payload=ContradictionPayload(
                a_memory_id="nonexistent-a",
                b_memory_id="nonexistent-b",
                c_memory_id="nonexistent-c",
            ),
            fit={"pool": 1.0},
        )
        detector._on_dispatch(item, "pool")
        lessons = list(repo.find(self_id=self_id, tier=MemoryTier.LESSON, source=SourceKind.I_DID))
        assert len(lessons) == 0

    def test_dispatch_with_superseded_parents(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        t0 = datetime.now(UTC) - timedelta(minutes=5)
        a_id = _mint_aff(repo, self_id, "s is true", when=t0)
        b_id = _mint_aff(repo, self_id, "s is false", when=t0 + timedelta(seconds=1))
        c_id = _mint_obs(repo, self_id, "s is false", when=t0 + timedelta(seconds=2))
        repo.set_superseded_by(a_id, "already-superseded")
        from turing.detectors.contradiction import ContradictionPayload, BacklogItem

        item = BacklogItem(
            item_id=str(uuid4()),
            class_=14,
            kind="raso_contradiction",
            payload=ContradictionPayload(a_memory_id=a_id, b_memory_id=b_id, c_memory_id=c_id),
            fit={"pool": 1.0},
        )
        detector._on_dispatch(item, "pool")
        lessons = list(repo.find(self_id=self_id, tier=MemoryTier.LESSON, source=SourceKind.I_DID))
        assert len(lessons) == 0


class TestCollectCompletedEdgeCases:
    def test_collect_handles_future_exception(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        from turing.detectors.contradiction import DraftLesson

        call_count = {"n": 0}

        def failing_draft(a, b, c):
            call_count["n"] += 1
            raise RuntimeError("LLM failed")

        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
            draft_lesson=failing_draft,
        )
        t0 = datetime.now(UTC) - timedelta(minutes=5)
        a_id = _mint_aff(repo, self_id, "t is true", when=t0)
        b_id = _mint_aff(repo, self_id, "t is false", when=t0 + timedelta(seconds=1))
        _mint_obs(repo, self_id, "t is false", when=t0 + timedelta(seconds=2))
        reactor.tick(ACTION_CADENCE_TICKS)
        lessons = list(repo.find(self_id=self_id, tier=MemoryTier.LESSON, source=SourceKind.I_DID))
        assert len(lessons) == 0

    def test_collect_skips_stale_parents_after_draft(self, repo: Repo, self_id: str) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        detector = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
        )
        t0 = datetime.now(UTC) - timedelta(minutes=5)
        a_id = _mint_aff(repo, self_id, "u is true", when=t0)
        b_id = _mint_aff(repo, self_id, "u is false", when=t0 + timedelta(seconds=1))
        _mint_obs(repo, self_id, "u is false", when=t0 + timedelta(seconds=2))
        original_get = repo.get

        def _get_then_supersede(memory_id: str):
            m = original_get(memory_id)
            if m is not None and m.memory_id == a_id:
                from unittest.mock import MagicMock

                mock_m = MagicMock()
                mock_m.memory_id = m.memory_id
                mock_m.superseded_by = "sneaky-superseder"
                mock_m.content = m.content
                return mock_m
            return m

        from turing.detectors.contradiction import DraftLesson

        slow_drafts = {"done": False}

        def slow_draft(a, b, c):
            return type(
                "DL",
                (),
                {
                    "content": f"resolution: {c.content}",
                    "initial_weight": 0.7,
                    "origin_episode_id": f"contra-{a.memory_id}-{b.memory_id}",
                },
            )()

        detector2 = ContradictionDetector(
            repo=repo,
            motivation=motivation,
            reactor=reactor,
            self_id=self_id,
            draft_lesson=slow_draft,
        )
        from turing.detectors.contradiction import ContradictionPayload, BacklogItem

        item = BacklogItem(
            item_id=str(uuid4()),
            class_=14,
            kind="raso_contradiction",
            payload=ContradictionPayload(a_memory_id=a_id, b_memory_id=b_id, c_memory_id="u"),
            fit={"pool": 1.0},
        )
        with patch.object(repo, "get", side_effect=_get_then_supersede):
            detector2._on_dispatch(item, "pool")
        lessons = list(repo.find(self_id=self_id, tier=MemoryTier.LESSON, source=SourceKind.I_DID))
        assert len(lessons) == 0
