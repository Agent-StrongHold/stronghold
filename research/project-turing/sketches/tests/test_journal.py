"""Tests for turing/runtime/journal.py — Journal.

Spec:
    Journal polls a Repo on a configurable cadence and writes:
      - narrative.md: chronological diary of REGRET, ACCOMPLISHMENT,
        AFFIRMATION, WISDOM, LESSON, and dream-session entries.
      - identity.md: current WISDOM claims, rewritten when the set changes.

Acceptance criteria:
    1. On construction, narrative.md is created with a header.
    2. identity.md is created (empty wisdom state).
    3. on_tick only polls at multiples of poll_ticks.
    4. New durable entries (REGRET, ACCOMPLISHMENT, AFFIRMATION, WISDOM)
       are appended to narrative.md in chronological order.
    5. LESSON entries are appended.
    6. Dream session markers (OBSERVATION with "dream session" + "completed"
       or "truncated") are appended.
    7. _last_seen advances to the max timestamp of written entries.
    8. identity.md is rewritten when WISDOM set changes.
    9. identity.md is unchanged when WISDOM set is the same.
    10. Poll failures are logged but do not raise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from turing.repo import Repo
from turing.runtime.journal import Journal
from turing.self_identity import bootstrap_self_id
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _mk_id() -> str:
    return str(uuid.uuid4())


def _durable(
    self_id: str,
    tier: MemoryTier,
    content: str,
    *,
    weight: float = 0.8,
    affect: float = 0.0,
    intent_at_time: str = "testing",
    context: dict | None = None,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=_mk_id(),
        self_id=self_id,
        tier=tier,
        source=SourceKind.I_DID,
        content=content,
        weight=weight,
        affect=affect,
        intent_at_time=intent_at_time,
        context=context or {},
    )


def _observation(
    self_id: str,
    content: str,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=_mk_id(),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=content,
        weight=0.3,
    )


def _lesson(
    self_id: str,
    content: str,
) -> EpisodicMemory:
    return EpisodicMemory(
        memory_id=_mk_id(),
        self_id=self_id,
        tier=MemoryTier.LESSON,
        source=SourceKind.I_DID,
        content=content,
        weight=0.6,
    )


@pytest.fixture
def journal_repo() -> Repo:
    r = Repo(None)
    yield r
    r.close()


@pytest.fixture
def journal_sid(journal_repo: Repo) -> str:
    return bootstrap_self_id(journal_repo.conn)


@pytest.fixture
def journal_dir(tmp_path: Path) -> Path:
    return tmp_path / "journal"


class TestJournalInit:
    def test_creates_narrative_md(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir)
        narrative = journal_dir / "narrative.md"
        assert narrative.exists()
        text = narrative.read_text()
        assert "Project Turing" in text
        assert journal_sid in text

    def test_creates_identity_md(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir)
        identity = journal_dir / "identity.md"
        assert identity.exists()
        text = identity.read_text()
        assert "no WISDOM yet" in text

    def test_creates_journal_dir(
        self, journal_repo: Repo, journal_sid: str, tmp_path: Path
    ) -> None:
        deep_dir = tmp_path / "a" / "b" / "c"
        Journal(repo=journal_repo, self_id=journal_sid, journal_dir=deep_dir)
        assert deep_dir.is_dir()

    def test_does_not_overwrite_existing_narrative(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        narrative = journal_dir / "narrative.md"
        journal_dir.mkdir(parents=True, exist_ok=True)
        narrative.write_text("old content")
        Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir)
        assert narrative.read_text() == "old content"


class TestJournalOnTick:
    def test_on_tick_skips_non_poll_ticks(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=100)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "r1"))
        j.on_tick(1)
        j.on_tick(50)
        narrative = journal_dir / "narrative.md"
        text = narrative.read_text()
        assert "r1" not in text

    def test_on_tick_polls_at_multiple(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=10)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "r1"))
        j.on_tick(10)
        narrative = journal_dir / "narrative.md"
        assert "r1" in narrative.read_text()

    def test_poll_failure_does_not_raise(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.close()
        j.on_tick(1)


class TestJournalDurableEntries:
    def test_regret_appended(self, journal_repo: Repo, journal_sid: str, journal_dir: Path) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "I rushed"))
        j.on_tick(1)
        narrative = journal_dir / "narrative.md"
        text = narrative.read_text()
        assert "I rushed" in text
        assert "regret" in text

    def test_accomplishment_appended(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.ACCOMPLISHMENT, "shipped feature"))
        j.on_tick(1)
        assert "shipped feature" in (journal_dir / "narrative.md").read_text()

    def test_affirmation_appended(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.AFFIRMATION, "I will test"))
        j.on_tick(1)
        assert "I will test" in (journal_dir / "narrative.md").read_text()

    def test_durable_renders_weight(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "heavy regret", weight=0.95))
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "weight 0.95" in text

    def test_durable_renders_affect(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "sad", affect=-0.5))
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "affect" in text

    def test_durable_renders_intent(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(
            _durable(journal_sid, MemoryTier.REGRET, "regretful", intent_at_time="fix bug")
        )
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "fix bug" in text

    def test_chronological_order(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        t1 = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 4, 1, 11, 0, 0, tzinfo=UTC)
        journal_repo.insert(
            EpisodicMemory(
                memory_id=_mk_id(),
                self_id=journal_sid,
                tier=MemoryTier.REGRET,
                source=SourceKind.I_DID,
                content="second",
                weight=0.7,
                created_at=t2,
            )
        )
        journal_repo.insert(
            EpisodicMemory(
                memory_id=_mk_id(),
                self_id=journal_sid,
                tier=MemoryTier.REGRET,
                source=SourceKind.I_DID,
                content="first",
                weight=0.7,
                created_at=t1,
            )
        )
        j._last_seen = t1 - timedelta(seconds=1)
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        first_pos = text.index("first")
        second_pos = text.index("second")
        assert first_pos < second_pos


class TestJournalLessons:
    def test_lesson_appended(self, journal_repo: Repo, journal_sid: str, journal_dir: Path) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_lesson(journal_sid, "always test edge cases"))
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "always test edge cases" in text
        assert "lesson" in text


class TestJournalDreams:
    def test_dream_completed_appended(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_observation(journal_sid, "dream session completed: 5 insights"))
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "dream session" in text
        assert "dream session completed: 5 insights" in text

    def test_dream_truncated_appended(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_observation(journal_sid, "dream session truncated after timeout"))
        j.on_tick(1)
        assert "dream session truncated" in (journal_dir / "narrative.md").read_text()

    def test_non_dream_observation_ignored(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_observation(journal_sid, "just a regular observation"))
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "regular observation" not in text

    def test_dream_without_status_ignored(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_observation(journal_sid, "dream session started"))
        j.on_tick(1)
        text = (journal_dir / "narrative.md").read_text()
        assert "dream session started" not in text


class TestJournalIdentity:
    def test_identity_updates_with_wisdom(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        marker_id = _mk_id()
        obs = EpisodicMemory(
            memory_id=marker_id,
            self_id=journal_sid,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="dream session completed",
            weight=0.3,
            origin_episode_id=marker_id,
        )
        journal_repo.insert(obs)
        wisdom = EpisodicMemory(
            memory_id=_mk_id(),
            self_id=journal_sid,
            tier=MemoryTier.WISDOM,
            source=SourceKind.I_DID,
            content="I am patient",
            weight=0.95,
            origin_episode_id=marker_id,
            context={"supersedes_via_lineage": [marker_id]},
        )
        journal_repo.insert(wisdom)
        j.on_tick(1)
        identity_text = (journal_dir / "identity.md").read_text()
        assert "I am patient" in identity_text
        assert "Things I have come to know" in identity_text

    def test_identity_shows_lineage_count(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        marker_id = _mk_id()
        obs = EpisodicMemory(
            memory_id=marker_id,
            self_id=journal_sid,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="dream session completed",
            weight=0.3,
            origin_episode_id=marker_id,
        )
        journal_repo.insert(obs)
        mem_id_1 = _mk_id()
        journal_repo.insert(
            EpisodicMemory(
                memory_id=mem_id_1,
                self_id=journal_sid,
                tier=MemoryTier.LESSON,
                source=SourceKind.I_DID,
                content="lesson1",
                weight=0.6,
            )
        )
        mem_id_2 = _mk_id()
        journal_repo.insert(
            EpisodicMemory(
                memory_id=mem_id_2,
                self_id=journal_sid,
                tier=MemoryTier.LESSON,
                source=SourceKind.I_DID,
                content="lesson2",
                weight=0.6,
            )
        )
        wisdom = EpisodicMemory(
            memory_id=_mk_id(),
            self_id=journal_sid,
            tier=MemoryTier.WISDOM,
            source=SourceKind.I_DID,
            content="I learn from mistakes",
            weight=0.92,
            origin_episode_id=marker_id,
            context={"supersedes_via_lineage": [marker_id, mem_id_1, mem_id_2]},
        )
        journal_repo.insert(wisdom)
        j.on_tick(1)
        identity_text = (journal_dir / "identity.md").read_text()
        assert "3 contributing experiences" in identity_text

    def test_identity_stable_when_wisdom_unchanged(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        marker_id = _mk_id()
        obs = EpisodicMemory(
            memory_id=marker_id,
            self_id=journal_sid,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="dream session completed",
            weight=0.3,
            origin_episode_id=marker_id,
        )
        journal_repo.insert(obs)
        wisdom = EpisodicMemory(
            memory_id=_mk_id(),
            self_id=journal_sid,
            tier=MemoryTier.WISDOM,
            source=SourceKind.I_DID,
            content="I am calm",
            weight=0.93,
            origin_episode_id=marker_id,
            context={"supersedes_via_lineage": [marker_id]},
        )
        journal_repo.insert(wisdom)
        j.on_tick(1)
        first_text = (journal_dir / "identity.md").read_text()
        j.on_tick(2)
        second_text = (journal_dir / "identity.md").read_text()
        assert first_text == second_text


class TestJournalIncrementalPoll:
    def test_only_new_entries_appended(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "old regret"))
        j.on_tick(1)
        text_after_first = (journal_dir / "narrative.md").read_text()
        assert "old regret" in text_after_first
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "new regret"))
        j.on_tick(2)
        text_after_second = (journal_dir / "narrative.md").read_text()
        assert "new regret" in text_after_second
        assert text_after_second.count("old regret") == 1

    def test_no_new_entries_identity_still_refreshed(
        self, journal_repo: Repo, journal_sid: str, journal_dir: Path
    ) -> None:
        j = Journal(repo=journal_repo, self_id=journal_sid, journal_dir=journal_dir, poll_ticks=1)
        journal_repo.insert(_durable(journal_sid, MemoryTier.REGRET, "r1"))
        j.on_tick(1)
        text_after = (journal_dir / "narrative.md").read_text()
        assert "r1" in text_after
        j.on_tick(2)
        assert (journal_dir / "narrative.md").read_text() == text_after


class TestJournalExtractTimestamps:
    def test_extract_from_rendered_entry(self) -> None:
        from turing.runtime.journal import _render_durable

        m = EpisodicMemory(
            memory_id=_mk_id(),
            self_id="s1",
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
            content="oops",
            weight=0.7,
            intent_at_time="test",
            created_at=datetime(2026, 4, 19, 3, 45, 0, tzinfo=UTC),
        )
        rendered = _render_durable(m, "regret")
        j = Journal.__new__(Journal)
        timestamps = j._extract_timestamps([rendered])
        assert len(timestamps) == 1
        assert "2026-04-19T03:45:00+00:00" == timestamps[0]
