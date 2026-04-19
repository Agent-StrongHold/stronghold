"""Tests for runtime/inspect.py."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from turing.repo import Repo
from turing.runtime.inspect import main
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


def test_summarize_prints_counts(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    db_path = tmp_path / "turing.db"
    _seed_db(db_path)

    rc = main(["--db", str(db_path), "summarize"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "episodic_memory" in out
    assert "durable_memory" in out
    assert "regret" in out.lower()
    assert "accomplishment" in out.lower()


def test_daydream_sessions_lists_imagined(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    db_path = tmp_path / "turing.db"
    _seed_db(db_path)

    rc = main(["--db", str(db_path), "daydream-sessions"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "daydream session" in out
    assert "what if I had routed" in out


def test_lineage_walks(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    db_path = tmp_path / "turing.db"
    _, regret_id, _ = _seed_db(db_path)

    rc = main(["--db", str(db_path), "lineage", regret_id])
    out = capsys.readouterr().out
    assert rc == 0
    assert regret_id[:8] in out
    assert "regret" in out.lower()


def test_lineage_unknown_id_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    db_path = tmp_path / "turing.db"
    _seed_db(db_path)

    rc = main(["--db", str(db_path), "lineage", "no-such-id"])
    assert rc == 1


def test_dispatch_log_prints_observations(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    db_path = tmp_path / "turing.db"
    _seed_db(db_path)

    rc = main(["--db", str(db_path), "dispatch-log", "--limit", "10"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "daydream session" in out
