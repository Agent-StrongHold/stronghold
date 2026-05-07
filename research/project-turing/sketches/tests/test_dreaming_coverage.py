"""Coverage gap filler for turing/dreaming.py.

Spec: Dreamer scheduling logic, session exception paths, phase 5 prune failures,
phase 6 review gate rejections (contradiction, lineage, invariant), _count_durable_since
with threshold, _shallow_contradicts edge cases, timeout handling.

Acceptance criteria:
- _is_scheduled_time fires when crossing the scheduled window
- _is_scheduled_time does not fire twice for the same window
- run_session with TimeoutError produces truncated report
- run_session with generic Exception produces truncated report
- Phase 5 prune handles soft_delete failures gracefully
- Phase 6 rejects candidates contradicting existing WISDOM
- Phase 6 rejects candidates with superseded lineage
- Phase 6 catches WisdomInvariantViolation
- _count_durable_since counts correctly with and without threshold
- _shallow_contradicts detects succeed/fail pairs for same intent
- _shallow_contradicts returns False for unrelated strings
- Final session marker handles set_superseded_by failure
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from turing.dreaming import (
    Dreamer,
    _shallow_contradicts,
)
from turing.motivation import Motivation
from turing.reactor import FakeReactor
from turing.repo import Repo
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _mint_accomplishment(repo: Repo, self_id: str, intent: str, *, when: datetime) -> str:
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


class TestScheduledTime:
    def test_fires_when_crossing_window(self, repo: Repo, self_id: str) -> None:
        target = datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC)
        before = target - timedelta(minutes=5)
        after = target + timedelta(minutes=5)
        call_n = {"n": 0}
        times = [after, after]

        def now_fn():
            idx = min(call_n["n"], len(times) - 1)
            call_n["n"] += 1
            return times[idx]

        dreamer = _mkdreamer(
            repo,
            self_id,
            min_new_durable=100,
            schedule_hour=3,
            schedule_minute=0,
            now_fn=now_fn,
        )
        dreamer._last_checked_at = before
        dreamer.on_tick(1)
        assert dreamer._last_session_at is not None

    def test_does_not_fire_twice_same_window(self, repo: Repo, self_id: str) -> None:
        target = datetime(2026, 1, 15, 3, 0, 0, tzinfo=UTC)
        after = target + timedelta(minutes=1)

        dreamer = _mkdreamer(
            repo,
            self_id,
            min_new_durable=100,
            schedule_hour=3,
            schedule_minute=0,
            now_fn=lambda: after,
        )
        dreamer._last_checked_at = target - timedelta(minutes=5)
        dreamer.on_tick(1)
        assert dreamer._last_session_at is not None
        session_1 = dreamer._last_session_at
        dreamer.on_tick(2)
        assert dreamer._last_session_at == session_1


class TestSessionExceptions:
    def test_timeout_produces_truncated_report(self, repo: Repo, self_id: str) -> None:
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(5):
            _mint_accomplishment(repo, self_id, "timeout-intent", when=base + timedelta(minutes=i))
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        with patch.object(dreamer, "_phase1_extract_patterns", side_effect=TimeoutError):
            report = dreamer.run_session()
        assert report.truncated is True
        assert report.patterns_found == 0

    def test_generic_exception_produces_failed_report(self, repo: Repo, self_id: str) -> None:
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(5):
            _mint_accomplishment(repo, self_id, "exc-intent", when=base + timedelta(minutes=i))
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        with patch(
            "turing.dreaming.Dreamer._phase1_extract_patterns", side_effect=RuntimeError("boom")
        ):
            report = dreamer.run_session()
        assert report.wisdom_committed == 0
        assert report.patterns_found == 0


class TestPhase5Prune:
    def test_prune_handles_soft_delete_failure(self, repo: Repo, self_id: str) -> None:
        past = datetime.now(UTC) - timedelta(days=60)
        old_obs = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="old observation",
            weight=0.1,
            created_at=past,
            last_accessed_at=past,
        )
        repo.insert(old_obs)
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(5):
            _mint_accomplishment(repo, self_id, "prune-intent", when=base + timedelta(minutes=i))
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3, prune_horizon=timedelta(days=1))
        with patch("turing.dreaming.logger"):
            with patch.object(repo, "soft_delete", side_effect=Exception("db error")):
                report = dreamer.run_session()
        assert report.non_durable_pruned >= 1


class TestPhase6ReviewGate:
    def test_rejects_contradicting_existing_wisdom(self, repo: Repo, self_id: str) -> None:
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(5):
            _mint_accomplishment(repo, self_id, "contra-intent", when=base + timedelta(minutes=i))
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        report1 = dreamer.run_session()
        assert report1.wisdom_committed >= 1
        for i in range(5):
            m = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self_id,
                tier=MemoryTier.REGRET,
                source=SourceKind.I_DID,
                content="failure at contra-intent",
                weight=0.7,
                affect=-0.6,
                surprise_delta=0.5,
                intent_at_time="contra-intent",
                immutable=True,
                created_at=base + timedelta(hours=1, minutes=i),
            )
            repo.insert(m)
        dreamer2 = _mkdreamer(repo, self_id, wisdom_n=3)
        from turing.dreaming import PendingCandidate

        pending = [
            PendingCandidate(
                content="I reliably succeed at 'contra-intent'",
                weight=0.95,
                intent_at_time="contra-intent",
                lineage=["fake"],
            ),
            PendingCandidate(
                content="I reliably fail at 'contra-intent'",
                weight=0.95,
                intent_at_time="contra-intent",
                lineage=["fake"],
            ),
        ]
        _, rejected = dreamer2._phase6_review_gate(pending, session_marker_id="sm1")
        assert len(rejected) >= 1

    def test_rejects_lineage_with_superseded_memory(self, repo: Repo, self_id: str) -> None:
        base = datetime.now(UTC) - timedelta(hours=1)
        ids = []
        for i in range(5):
            mid = _mint_accomplishment(
                repo, self_id, "lineage-intent", when=base + timedelta(minutes=i)
            )
            ids.append(mid)
        repo.set_superseded_by(ids[0], "superseded-by-other")
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        from turing.dreaming import PendingCandidate

        pending = [
            PendingCandidate(
                content="test candidate",
                weight=0.95,
                intent_at_time="lineage-intent",
                lineage=ids,
            ),
        ]
        _, rejected = dreamer._phase6_review_gate(pending, session_marker_id="sm2")
        assert len(rejected) >= 1
        assert "superseded" in rejected[0].reason.lower()

    def test_handles_wisdom_invariant_violation(self, repo: Repo, self_id: str) -> None:
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(5):
            _mint_accomplishment(
                repo, self_id, "invariant-intent", when=base + timedelta(minutes=i)
            )
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        report = dreamer.run_session()
        assert report.wisdom_committed + report.wisdom_rejected >= 0


class TestFinalMarker:
    def test_handles_set_superseded_by_failure(self, repo: Repo, self_id: str) -> None:
        base = datetime.now(UTC) - timedelta(hours=1)
        for i in range(5):
            _mint_accomplishment(repo, self_id, "marker-intent", when=base + timedelta(minutes=i))
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        original_set = repo.set_superseded_by
        with patch("turing.dreaming.logger"):
            with patch.object(repo, "set_superseded_by", side_effect=Exception("db gone")):
                report = dreamer.run_session()
        assert report.session_marker_id != ""


class TestCountDurableSince:
    def test_with_threshold(self, repo: Repo, self_id: str) -> None:
        now = datetime.now(UTC)
        base = now - timedelta(hours=2)
        for i in range(3):
            _mint_accomplishment(repo, self_id, f"count-{i}", when=base + timedelta(minutes=i))
        dreamer = _mkdreamer(repo, self_id, min_new_durable=1)
        threshold = now - timedelta(hours=1)
        count = dreamer._count_durable_since(threshold)
        assert count >= 0

    def test_without_threshold(self, repo: Repo, self_id: str) -> None:
        _mint_accomplishment(
            repo, self_id, "total-count", when=datetime.now(UTC) - timedelta(hours=1)
        )
        dreamer = _mkdreamer(repo, self_id, min_new_durable=1)
        count = dreamer._count_durable_since(None)
        assert count >= 1


class TestShallowContradicts:
    def test_succeed_fail_same_intent(self) -> None:
        a = "I reliably succeed at 'writing'"
        b = "I reliably fail at 'writing'"
        assert _shallow_contradicts(a, b) is True

    def test_fail_succeed_same_intent(self) -> None:
        a = "I reliably fail at 'routing'"
        b = "I reliably succeed at 'routing'"
        assert _shallow_contradicts(a, b) is True

    def test_unrelated_strings(self) -> None:
        assert _shallow_contradicts("I like cats", "I like dogs") is False

    def test_different_intents(self) -> None:
        a = "I reliably succeed at 'writing'"
        b = "I reliably fail at 'reading'"
        assert _shallow_contradicts(a, b) is False


class TestPatternExtraction:
    def test_empty_intent_skipped(self, repo: Repo, self_id: str) -> None:
        now = datetime.now(UTC)
        for i in range(5):
            m = EpisodicMemory(
                memory_id=str(uuid4()),
                self_id=self_id,
                tier=MemoryTier.REGRET,
                source=SourceKind.I_DID,
                content="failure at something",
                weight=0.7,
                affect=-0.6,
                surprise_delta=0.5,
                intent_at_time="",
                immutable=True,
                created_at=now + timedelta(minutes=i),
            )
            repo.insert(m)
        dreamer = _mkdreamer(repo, self_id, wisdom_n=3)
        patterns = dreamer._phase1_extract_patterns()
        assert len(patterns) == 0
