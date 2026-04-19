"""Tests for specs/detectors/contradiction.md: AC-D1.1 through AC-D1.10 (subset)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from turing.detectors.contradiction import (
    ContradictionDetector,
    _claims_opposed,
    _supports_one_side,
)
from turing.motivation import ACTION_CADENCE_TICKS, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.types import EpisodicMemory, MemoryTier, SourceKind


INTENT = "route-writing-request"


# -----------------------------------------------------------------------------
# Structural checks (unit-level).
# -----------------------------------------------------------------------------


def test_claims_opposed_true_false_suffix() -> None:
    assert _claims_opposed("artificer fits here is true", "artificer fits here is false")
    assert _claims_opposed("artificer fits here is false", "artificer fits here is true")


def test_claims_opposed_rejects_equal() -> None:
    assert _claims_opposed("x is true", "x is true") is False


def test_supports_one_side() -> None:
    assert _supports_one_side("x is true", "x is true", "x is false")
    assert _supports_one_side("x is false", "x is true", "x is false")
    assert not _supports_one_side("unrelated", "x is true", "x is false")


# -----------------------------------------------------------------------------
# AC-D1.3 — no resolution → no candidate.
# AC-D1.1 — full triple → one candidate.
# AC-D1.2 — idempotent: same triple does not submit twice.
# -----------------------------------------------------------------------------


def _mint_aff(
    repo: Repo, self_id: str, content: str, *, when: datetime | None = None
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.AFFIRMATION,
        source=SourceKind.I_DID,
        content=content,
        weight=0.7,
        intent_at_time=INTENT,
        created_at=when or datetime.now(UTC),
    )
    repo.insert(m)
    return m.memory_id


def _mint_obs(
    repo: Repo, self_id: str, content: str, *, when: datetime | None = None
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=content,
        weight=0.3,
        intent_at_time=INTENT,
        created_at=when or datetime.now(UTC),
    )
    repo.insert(m)
    return m.memory_id


def test_ac_d1_3_no_resolution_no_candidate(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    detector = ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )

    _mint_aff(repo, self_id, "artificer fits here is true")
    _mint_aff(repo, self_id, "artificer fits here is false")

    reactor.tick(1)
    assert not any(b.kind == "raso_contradiction" for b in motivation.backlog)


def test_ac_d1_1_full_triple_submits_candidate(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    detector = ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )

    t0 = datetime.now(UTC) - timedelta(minutes=10)
    t1 = datetime.now(UTC) - timedelta(minutes=9)
    t2 = datetime.now(UTC) - timedelta(minutes=5)
    _mint_aff(repo, self_id, "artificer fits here is true", when=t0)
    _mint_aff(repo, self_id, "artificer fits here is false", when=t1)
    _mint_obs(repo, self_id, "artificer fits here is false", when=t2)

    reactor.tick(1)
    candidates = [b for b in motivation.backlog if b.kind == "raso_contradiction"]
    assert len(candidates) == 1


def test_ac_d1_2_idempotent_over_repeated_ticks(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    detector = ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )

    t0 = datetime.now(UTC) - timedelta(minutes=10)
    t1 = datetime.now(UTC) - timedelta(minutes=9)
    t2 = datetime.now(UTC) - timedelta(minutes=5)
    _mint_aff(repo, self_id, "x is true", when=t0)
    _mint_aff(repo, self_id, "x is false", when=t1)
    _mint_obs(repo, self_id, "x is true", when=t2)

    reactor.tick(1)
    reactor.tick(1)
    reactor.tick(1)
    candidates = [b for b in motivation.backlog if b.kind == "raso_contradiction"]
    assert len(candidates) == 1


# -----------------------------------------------------------------------------
# AC-D1.8, AC-D1.9 — dispatched execution mints LESSON with lineage chain.
# -----------------------------------------------------------------------------


def test_ac_d1_8_dispatched_mints_lesson(repo: Repo, self_id: str) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    detector = ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )

    t0 = datetime.now(UTC) - timedelta(minutes=10)
    t1 = datetime.now(UTC) - timedelta(minutes=9)
    t2 = datetime.now(UTC) - timedelta(minutes=5)
    a_id = _mint_aff(repo, self_id, "y is true", when=t0)
    b_id = _mint_aff(repo, self_id, "y is false", when=t1)
    c_id = _mint_obs(repo, self_id, "y is false", when=t2)

    reactor.tick(ACTION_CADENCE_TICKS)

    lessons = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.LESSON,
            source=SourceKind.I_DID,
        )
    )
    assert len(lessons) == 1
    lesson = lessons[0]
    assert lesson.supersedes in {a_id, b_id}
    assert {a_id, b_id}.issubset(
        set(lesson.context.get("supersedes_via_lineage", []))
    )
    assert lesson.context.get("resolution_observation") == c_id


def test_ac_d1_9_both_parents_superseded_by_lesson(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    detector = ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )

    t0 = datetime.now(UTC) - timedelta(minutes=10)
    t1 = datetime.now(UTC) - timedelta(minutes=9)
    t2 = datetime.now(UTC) - timedelta(minutes=5)
    a_id = _mint_aff(repo, self_id, "z is true", when=t0)
    b_id = _mint_aff(repo, self_id, "z is false", when=t1)
    _mint_obs(repo, self_id, "z is true", when=t2)

    reactor.tick(ACTION_CADENCE_TICKS)

    a_reloaded = repo.get(a_id)
    b_reloaded = repo.get(b_id)
    assert a_reloaded is not None and b_reloaded is not None
    assert a_reloaded.superseded_by is not None
    assert b_reloaded.superseded_by is not None
    assert a_reloaded.superseded_by == b_reloaded.superseded_by
