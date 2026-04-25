"""Coverage gap filler for turing/runtime/inspect.py.

Spec: cmd_pressure with unreachable URL, _print_section with missing table and
empty table, lineage forward chain with superseded_by, cmd_daydream_sessions
with None origin_episode_id, cmd_summarize with self_id present, build_parser.

Acceptance criteria:
- cmd_pressure returns 1 when metrics URL unreachable
- _print_section handles missing table gracefully
- _print_section handles empty table
- cmd_lineage walks forward chain via superseded_by
- cmd_daydream_sessions handles None origin_episode_id
- cmd_summarize prints self_id when present
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from turing.repo import Repo
from turing.runtime.inspect import (
    _fetch_memory,
    _print_section,
    build_parser,
    cmd_daydream_sessions,
    cmd_lineage,
    cmd_pressure,
    cmd_summarize,
    main,
)
from turing.self_identity import bootstrap_self_id
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _seed_db(path: Path) -> tuple[str, str, str]:
    repo = Repo(str(path))
    self_id = bootstrap_self_id(repo.conn)
    regret = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="I regret the way I routed that thing",
        weight=0.7,
        affect=-0.6,
        surprise_delta=0.5,
        intent_at_time="route-x",
        immutable=True,
    )
    repo.insert(regret)
    accomplishment = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.ACCOMPLISHMENT,
        source=SourceKind.I_DID,
        content="I nailed that delegation",
        weight=0.7,
        affect=0.6,
        surprise_delta=0.4,
        intent_at_time="route-y",
        immutable=True,
    )
    repo.insert(accomplishment)
    marker = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content=f"daydream session abc on pool=fake, writes=1, seed={regret.memory_id}",
        weight=0.2,
        origin_episode_id="session-abc",
    )
    repo.insert(marker)
    imagined = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.HYPOTHESIS,
        source=SourceKind.I_IMAGINED,
        content="what if I had routed X to Scribe",
        weight=0.3,
        intent_at_time="route-x",
        origin_episode_id="session-abc",
    )
    repo.insert(imagined)
    repo.close()
    return self_id, regret.memory_id, accomplishment.memory_id


class TestPressureCommand:
    def test_unreachable_url_returns_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        db_path = tmp_path / "turing.db"
        _seed_db(db_path)
        args = build_parser().parse_args(
            ["--db", str(db_path), "pressure", "--metrics-url", "http://127.0.0.1:1/metrics"]
        )
        rc = cmd_pressure(args)
        assert rc == 1


class TestPrintSection:
    def test_missing_table(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE self_identity (self_id TEXT)")
        _print_section(conn, "nonexistent_table", "tier, source")
        out = capsys.readouterr().out
        assert "missing or empty" in out
        conn.close()

    def test_empty_table(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE episodic_memory (tier TEXT, source TEXT, content TEXT)")
        _print_section(conn, "episodic_memory", "tier, source")
        out = capsys.readouterr().out
        assert "empty" in out
        conn.close()


class TestLineageForwardChain:
    def test_walks_superseded_by_chain(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "turing.db"
        repo = Repo(str(db_path))
        self_id = bootstrap_self_id(repo.conn)
        original = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
            content="original regret",
            weight=0.7,
            affect=-0.6,
            intent_at_time="test",
            immutable=True,
        )
        repo.insert(original)
        lesson = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.LESSON,
            source=SourceKind.I_DID,
            content="learned from regret",
            weight=0.7,
            intent_at_time="test",
            supersedes=original.memory_id,
        )
        repo.insert(lesson)
        repo.set_superseded_by(original.memory_id, lesson.memory_id)
        repo.close()
        rc = main(["--db", str(db_path), "lineage", original.memory_id])
        out = capsys.readouterr().out
        assert rc == 0
        assert "lesson" in out.lower()


class TestDaydreamSessionsNoneOrigin:
    def test_none_origin_episode_id(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "turing.db"
        repo = Repo(str(db_path))
        self_id = bootstrap_self_id(repo.conn)
        marker = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=self_id,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="daydream session no-origin",
            weight=0.2,
            origin_episode_id=None,
        )
        repo.insert(marker)
        repo.close()
        rc = main(["--db", str(db_path), "daydream-sessions", "--limit", "10"])
        assert rc == 0


class TestSummarizeWithSelfId:
    def test_prints_self_id(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        db_path = tmp_path / "turing.db"
        _seed_db(db_path)
        rc = main(["--db", str(db_path), "summarize"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "self_id" in out
