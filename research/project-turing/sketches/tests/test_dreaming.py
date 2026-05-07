"""Tests for turing/dreaming.py: Dreamer sessions, phases, invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from turing.dreaming import Dreamer
from turing.motivation import Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo, WisdomInvariantViolation
from turing.tiers import WEIGHT_BOUNDS
from turing.types import EpisodicMemory, MemoryTier, SourceKind


# --- helpers --------------------------------------------------------------


def _mint_accomplishment(
    repo: Repo, self_id: str, intent: str, *, when: datetime
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.ACCOMPLISHMENT,
        source=SourceKind.I_DID,
        content=f"success at {intent}",
        weight=0.7,
        affect=0.6,
        confidence_at_creation=0.7,
        surprise_delta=0.4,
        intent_at_time=intent,
        immutable=True,
        created_at=when,
    )
    repo.insert(m)
    return m.memory_id


def _mint_regret(
    repo: Repo, self_id: str, intent: str, *, when: datetime
) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content=f"failure at {intent}",
        weight=0.7,
        affect=-0.6,
        confidence_at_creation=0.7,
        surprise_delta=0.5,
        intent_at_time=intent,
        immutable=True,
        created_at=when,
    )
    repo.insert(m)
    return m.memory_id


def _mkdreamer(repo: Repo, self_id: str, **kwargs) -> Dreamer:
    defaults = dict(min_new_durable=1, wisdom_n=3, max_candidates=3)
    defaults.update(kwargs)
    return Dreamer(
        motivation=Motivation(FakeReactor()),
        reactor=FakeReactor(),
        repo=repo,
        self_id=self_id,
        **defaults,
    )


# --- AC-12.2: skip when too little new durable ---------------------------


def test_session_skipped_when_insufficient_new_durable(
    repo: Repo, self_id: str
) -> None:
    dreamer = _mkdreamer(repo, self_id, min_new_durable=100)
    report = dreamer.run_session()
    assert report.session_marker_id == ""
    assert report.wisdom_committed == 0


# --- AC-12.5, 12.6: phase 1 + 2 produce pending candidates ---------------


def test_accomplishment_pattern_mints_wisdom_candidate(
    repo: Repo, self_id: str
) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(5):
        _mint_accomplishment(repo, self_id, "route-writing", when=base + timedelta(minutes=i))

    dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
    report = dreamer.run_session()

    assert report.patterns_found >= 1
    assert report.wisdom_committed >= 1
    wisdom = list(
        repo.find(
            self_id=self_id,
            tier=MemoryTier.WISDOM,
            source=SourceKind.I_DID,
        )
    )
    assert wisdom, "expected at least one committed WISDOM"
    for w in wisdom:
        assert w.origin_episode_id is not None
        assert w.context.get("supersedes_via_lineage"), "lineage required"


def test_regret_pattern_mints_wisdom_candidate(
    repo: Repo, self_id: str
) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(5):
        _mint_regret(repo, self_id, "route-failure", when=base + timedelta(minutes=i))

    dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
    report = dreamer.run_session()

    assert report.patterns_found >= 1
    assert report.wisdom_committed >= 1


def test_mixed_polarity_does_not_mint_wisdom(
    repo: Repo, self_id: str
) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(3):
        _mint_accomplishment(repo, self_id, "mixed", when=base + timedelta(minutes=i))
    for i in range(3):
        _mint_regret(repo, self_id, "mixed", when=base + timedelta(minutes=i + 10))

    dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
    report = dreamer.run_session()
    assert report.wisdom_committed == 0


# --- AC-12.16: candidate cap ---------------------------------------------


def test_wisdom_candidate_cap_enforced(repo: Repo, self_id: str) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    # Five distinct accomplishment intents, each with 5 successes.
    for intent_i in range(5):
        intent = f"intent-{intent_i}"
        for i in range(5):
            _mint_accomplishment(
                repo,
                self_id,
                intent,
                when=base + timedelta(minutes=intent_i * 10 + i),
            )

    dreamer = _mkdreamer(repo, self_id, wisdom_n=3, max_candidates=2)
    report = dreamer.run_session()
    assert report.wisdom_committed <= 2


# --- AC-12.12, 12.14: WISDOM invariants enforced at repo -----------------


def test_wisdom_write_without_origin_rejected(
    repo: Repo, self_id: str
) -> None:
    wisdom = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.WISDOM,
        source=SourceKind.I_DID,
        content="x",
        weight=0.95,
        intent_at_time="i",
        context={"supersedes_via_lineage": ["fake"]},
        immutable=True,
    )
    with pytest.raises(WisdomInvariantViolation, match="origin_episode_id"):
        repo.insert(wisdom)


def test_wisdom_write_with_dangling_lineage_rejected(
    repo: Repo, self_id: str
) -> None:
    # Marker exists so origin resolves.
    marker = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content="dream session s1 completed",
        weight=0.2,
        origin_episode_id="s1",
    )
    repo.insert(marker)
    wisdom = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.WISDOM,
        source=SourceKind.I_DID,
        content="x",
        weight=0.95,
        intent_at_time="i",
        origin_episode_id="s1",
        context={"supersedes_via_lineage": ["does-not-exist"]},
        immutable=True,
    )
    with pytest.raises(WisdomInvariantViolation, match="unknown memory_id"):
        repo.insert(wisdom)


def test_wisdom_cannot_supersede_wisdom(repo: Repo, self_id: str) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(5):
        _mint_accomplishment(repo, self_id, "dom", when=base + timedelta(minutes=i))

    dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
    dreamer.run_session()

    wisdom = next(
        iter(
            repo.find(
                self_id=self_id,
                tier=MemoryTier.WISDOM,
                source=SourceKind.I_DID,
            )
        )
    )

    attempt = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.WISDOM,
        source=SourceKind.I_DID,
        content="attempt to supersede",
        weight=0.95,
        intent_at_time="dom",
        origin_episode_id=wisdom.origin_episode_id,
        supersedes=wisdom.memory_id,
        context={"supersedes_via_lineage": [wisdom.memory_id]},
        immutable=True,
    )
    with pytest.raises(WisdomInvariantViolation, match="may not supersede"):
        repo.insert(attempt)


# --- AC-12.11: session marker exists -------------------------------------


def test_session_writes_start_and_final_markers(
    repo: Repo, self_id: str
) -> None:
    base = datetime.now(UTC) - timedelta(hours=1)
    for i in range(5):
        _mint_accomplishment(repo, self_id, "markers", when=base + timedelta(minutes=i))

    dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
    dreamer.run_session()

    markers = [
        m
        for m in repo.find(
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
        )
        if "dream session" in m.content
    ]
    # At least two markers: placeholder + final (the final supersedes the placeholder).
    assert len(markers) >= 2
    final_markers = [m for m in markers if "completed" in m.content or "truncated" in m.content]
    assert final_markers, "expected a final marker"
