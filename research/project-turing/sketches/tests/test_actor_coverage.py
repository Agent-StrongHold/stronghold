"""Coverage gap filler for turing/runtime/actor.py.

Spec: Actor exception handling in on_tick, ToolNotPermitted handling,
_title_and_kind_for for all tier types, _body_for with context/lineage,
actor poll with no new events.

Acceptance criteria:
- Actor on_tick catches and logs exceptions from _poll_and_act
- Actor _write_obsidian catches ToolNotPermitted silently
- Actor _write_obsidian catches generic exceptions
- Actor _poll_and_act returns early when no events found
- _title_and_kind_for returns correct format for WISDOM, REGRET, ACCOMPLISHMENT, AFFIRMATION, and fallback
- _body_for includes intent, affect, surprise, and lineage when present
- _body_for omits fields when absent
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from turing.repo import Repo
from turing.runtime.actor import Actor, _title_and_kind_for, _body_for
from turing.runtime.tools.base import Tool, ToolMode, ToolNotPermitted, ToolRegistry
from turing.runtime.tools.obsidian import ObsidianWriter
from turing.tiers import WEIGHT_BOUNDS
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _mint_memory(
    repo: Repo,
    self_id: str,
    tier: MemoryTier,
    *,
    content: str = "test content",
    intent: str = "test-intent",
    affect: float = 0.0,
    surprise_delta: float = 0.0,
    context: dict | None = None,
    when: datetime | None = None,
    immutable: bool = False,
) -> str:
    weight = WEIGHT_BOUNDS[tier][0] + 0.05
    if tier == MemoryTier.WISDOM:
        immutable = True
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=tier,
        source=SourceKind.I_DID,
        content=content,
        weight=weight,
        affect=affect,
        surprise_delta=surprise_delta,
        intent_at_time=intent,
        context=context or {},
        immutable=immutable,
        created_at=when or datetime.now(UTC) + timedelta(seconds=1),
    )
    repo.insert(m)
    return m.memory_id


class FailingTool:
    name = "obsidian_writer"
    mode = ToolMode.WRITE

    def invoke(self, **kwargs: Any) -> Any:
        raise ToolNotPermitted("not allowed")


class ExplodingTool:
    name = "obsidian_writer"
    mode = ToolMode.WRITE

    def invoke(self, **kwargs: Any) -> Any:
        raise RuntimeError("kaboom")


class TestActorExceptionHandling:
    def test_on_tick_catches_poll_exception(self, repo: Repo, self_id: str, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianWriter(vault_dir=tmp_path))
        actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=1)
        with patch.object(actor, "_poll_and_act", side_effect=RuntimeError("boom")):
            actor.on_tick(1)

    def test_write_obsidian_catches_tool_not_permitted(self, repo: Repo, self_id: str) -> None:
        registry = ToolRegistry()
        registry.register(FailingTool())
        actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=1)
        _mint_memory(repo, self_id, MemoryTier.REGRET, immutable=True)
        actor.on_tick(1)

    def test_write_obsidian_catches_generic_exception(self, repo: Repo, self_id: str) -> None:
        registry = ToolRegistry()
        registry.register(ExplodingTool())
        actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=1)
        _mint_memory(repo, self_id, MemoryTier.REGRET, immutable=True)
        actor.on_tick(1)

    def test_poll_returns_early_no_events(self, repo: Repo, self_id: str) -> None:
        registry = ToolRegistry()
        actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=1)
        actor._last_seen = datetime.now(UTC) + timedelta(hours=1)
        actor._poll_and_act()


class TestTitleAndKindFor:
    def test_wisdom(self) -> None:
        m = SimpleNamespace(tier=MemoryTier.WISDOM, content="x" * 100)
        title, kind = _title_and_kind_for(m)
        assert title.startswith("WISDOM")
        assert kind == "wisdom"

    def test_regret(self) -> None:
        m = SimpleNamespace(tier=MemoryTier.REGRET, content="bad decision")
        title, kind = _title_and_kind_for(m)
        assert title.startswith("Regret")
        assert kind == "regret"

    def test_accomplishment(self) -> None:
        m = SimpleNamespace(tier=MemoryTier.ACCOMPLISHMENT, content="great success")
        title, kind = _title_and_kind_for(m)
        assert title.startswith("Accomplishment")
        assert kind == "accomplishment"

    def test_affirmation(self) -> None:
        m = SimpleNamespace(tier=MemoryTier.AFFIRMATION, content="commit to x")
        title, kind = _title_and_kind_for(m)
        assert title.startswith("Commitment")
        assert kind == "affirmation"

    def test_fallback_uses_tier_value(self) -> None:
        m = SimpleNamespace(tier=MemoryTier.OBSERVATION, content="noted")
        title, kind = _title_and_kind_for(m)
        assert kind == "observation"


class TestBodyFor:
    def test_with_all_fields(self) -> None:
        m = SimpleNamespace(
            content="did something",
            intent_at_time="my-intent",
            affect=0.5,
            surprise_delta=0.3,
            context={"supersedes_via_lineage": ["id1", "id2", "id3"]},
        )
        body = _body_for(m)
        assert "my-intent" in body
        assert "+0.50" in body
        assert "0.30" in body
        assert "3 contributing memories" in body

    def test_minimal_fields(self) -> None:
        m = SimpleNamespace(
            content="minimal",
            intent_at_time="",
            affect=0.0,
            surprise_delta=0.0,
            context={},
        )
        body = _body_for(m)
        assert body.strip() == "minimal"

    def test_lineage_not_list(self) -> None:
        m = SimpleNamespace(
            content="test",
            intent_at_time="",
            affect=0.0,
            surprise_delta=0.0,
            context={"supersedes_via_lineage": "not-a-list"},
        )
        body = _body_for(m)
        assert "contributing memories" not in body

    def test_empty_lineage_list(self) -> None:
        m = SimpleNamespace(
            content="test",
            intent_at_time="",
            affect=0.0,
            surprise_delta=0.0,
            context={"supersedes_via_lineage": []},
        )
        body = _body_for(m)
        assert "contributing memories" not in body
