"""Tests for specs/daydreaming.md: AC-7.1, 7.2, 7.3, 7.4, 7.6, 7.12, 7.13, 7.15."""

from __future__ import annotations

from uuid import uuid4

import pytest

from turing.daydream import DaydreamProducer, DaydreamWriter
from turing.motivation import ACTION_CADENCE_TICKS, Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo, WisdomInvariantViolation
from turing.tiers import WEIGHT_BOUNDS
from turing.types import EpisodicMemory, MemoryTier, SourceKind


# -----------------------------------------------------------------------------
# AC-7.1 — DaydreamWriter cannot emit I_DID.
# AC-7.2 — DaydreamWriter has no API for durable tiers.
# -----------------------------------------------------------------------------


def test_ac_7_1_daydream_writer_has_no_i_did_api(repo: Repo, self_id: str) -> None:
    writer = DaydreamWriter(repo, self_id, session_id="s")
    assert not hasattr(writer, "write_regret")
    assert not hasattr(writer, "write_i_did")
    # Only write_hypothesis and write_observation exist.
    assert hasattr(writer, "write_hypothesis")
    assert hasattr(writer, "write_observation")


def test_ac_7_1_daydream_writes_are_i_imagined(repo: Repo, self_id: str) -> None:
    writer = DaydreamWriter(repo, self_id, session_id="s1")
    mid = writer.write_hypothesis("what if X", intent="route-a-request")
    m = repo.get(mid)
    assert m is not None
    assert m.source == SourceKind.I_IMAGINED
    assert m.tier == MemoryTier.HYPOTHESIS


def test_ac_7_2_daydream_writer_cannot_reach_durable_tiers(
    repo: Repo, self_id: str
) -> None:
    # Even if someone constructs a durable memory and tries to insert via
    # the writer's repo handle, the durable-tier + I_IMAGINED combination
    # is rejected at construction (INV-3 via __post_init__).
    with pytest.raises(ValueError, match="requires source=i_did"):
        EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.REGRET,
            source=SourceKind.I_IMAGINED,
            content="c",
            weight=0.7,
            intent_at_time="i",
        )


def test_wisdom_tier_requires_dreaming_origin(repo: Repo, self_id: str) -> None:
    wisdom = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.WISDOM,
        source=SourceKind.I_DID,
        content="self-knowledge",
        weight=0.95,
        intent_at_time="self-description",
        immutable=True,
        # deliberately no origin_episode_id
    )
    with pytest.raises(WisdomInvariantViolation):
        repo.insert(wisdom)


# -----------------------------------------------------------------------------
# AC-7.4 — producer emits one candidate while pressure > 0 and none present.
# AC-7.7 — candidate is evicted when pool pressure drops to 0.
# -----------------------------------------------------------------------------


def test_ac_7_4_producer_emits_one_candidate_when_pressure_positive(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    motivation.set_pressure("gemini", 3000.0)
    _producer = DaydreamProducer(
        pool_name="gemini",
        self_id=self_id,
        motivation=motivation,
        reactor=reactor,
        repo=repo,
    )
    reactor.tick(1)
    candidates = [b for b in motivation.backlog if b.kind == "daydream_candidate"]
    assert len(candidates) == 1


def test_ac_7_4_producer_does_not_flood_candidates(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    motivation.set_pressure("gemini", 3000.0)
    _producer = DaydreamProducer(
        pool_name="gemini",
        self_id=self_id,
        motivation=motivation,
        reactor=reactor,
        repo=repo,
    )
    # Many ticks — still only one candidate.
    reactor.tick(100)
    candidates = [b for b in motivation.backlog if b.kind == "daydream_candidate"]
    # Either 1 (still waiting) or 0 (already dispatched and consumed).
    assert len(candidates) <= 1


def test_ac_7_7_candidate_evicted_when_pressure_zero(
    repo: Repo, self_id: str
) -> None:
    reactor = FakeReactor()
    motivation = Motivation(reactor)
    motivation.set_pressure("gemini", 3000.0)
    producer = DaydreamProducer(
        pool_name="gemini",
        self_id=self_id,
        motivation=motivation,
        reactor=reactor,
        repo=repo,
    )
    reactor.tick(1)
    assert producer._active_candidate_id is not None

    motivation.set_pressure("gemini", 0.0)
    reactor.tick(1)
    assert producer._active_candidate_id is None
    candidates = [b for b in motivation.backlog if b.kind == "daydream_candidate"]
    assert candidates == []


# -----------------------------------------------------------------------------
# AC-7.12 — session marker written with I_DID / OBSERVATION.
# AC-7.13 — determinism with a pinned imagine fn.
# -----------------------------------------------------------------------------


def _pinned_imagine(seed, retrieved, pool_name):
    return [
        ("hypothesis", f"what-if-A for {seed.memory_id}", seed.intent_at_time or "i"),
        ("hypothesis", f"what-if-B for {seed.memory_id}", seed.intent_at_time or "i"),
    ]


def _seed_regret(repo: Repo, self_id: str) -> str:
    regret = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="I regret X",
        weight=0.7,
        affect=-0.5,
        confidence_at_creation=0.8,
        surprise_delta=0.5,
        intent_at_time="route-a-thing",
        immutable=True,
    )
    repo.insert(regret)
    return regret.memory_id


def test_ac_7_12_session_marker_written(repo: Repo, self_id: str) -> None:
    _seed_regret(repo, self_id)

    reactor = FakeReactor()
    motivation = Motivation(reactor)
    motivation.set_pressure("gemini", PRESSURE_MAX := 5000.0)
    _producer = DaydreamProducer(
        pool_name="gemini",
        self_id=self_id,
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        imagine=_pinned_imagine,
    )

    # Drive enough ticks for the producer to emit and the sweep to dispatch.
    reactor.tick(ACTION_CADENCE_TICKS)

    markers = [
        m
        for m in repo.find(
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
        )
        if "daydream session" in m.content
    ]
    assert len(markers) >= 1


def test_ac_7_13_deterministic_output(repo: Repo, self_id: str) -> None:
    seed_id = _seed_regret(repo, self_id)

    reactor = FakeReactor()
    motivation = Motivation(reactor)
    motivation.set_pressure("gemini", 5000.0)
    _producer = DaydreamProducer(
        pool_name="gemini",
        self_id=self_id,
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        imagine=_pinned_imagine,
    )
    reactor.tick(ACTION_CADENCE_TICKS)

    imagined = [
        m
        for m in repo.find(
            self_id=self_id,
            tier=MemoryTier.HYPOTHESIS,
            source=SourceKind.I_IMAGINED,
        )
    ]
    contents = sorted(m.content for m in imagined)
    assert contents == [
        f"what-if-A for {seed_id}",
        f"what-if-B for {seed_id}",
    ]


# -----------------------------------------------------------------------------
# AC-7.15 — I_IMAGINED source is never upgraded to I_DID.
# -----------------------------------------------------------------------------


def test_ac_7_15_source_cannot_be_upgraded(repo: Repo, self_id: str) -> None:
    writer = DaydreamWriter(repo, self_id, session_id="s")
    mid = writer.write_hypothesis("what if", intent="i")
    m = repo.get(mid)
    assert m is not None
    with pytest.raises(AttributeError):
        m.source = SourceKind.I_DID
