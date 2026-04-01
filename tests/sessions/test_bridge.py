"""Tests for session-to-episodic memory bridge."""

from __future__ import annotations

import time

import pytest

from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.sessions.bridge import BRIDGE_MEMORY_WEIGHT, MIN_MESSAGES_FOR_BRIDGE, SessionBridge
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.memory import MemoryScope, MemoryTier

from tests.fakes import FakeLLMClient


def _make_messages(n: int) -> list[dict[str, str]]:
    """Build n alternating user/assistant messages."""
    msgs: list[dict[str, str]] = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"Message {i}"})
    return msgs


class TestBridgeSessionCreatesMemory:
    """bridge_session stores an episodic memory with correct attributes."""

    async def test_creates_episodic_memory(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store)

        messages = _make_messages(6)
        ok = await bridge.bridge_session(
            "org1/team1/user1:sess1",
            messages,
            org_id="org1",
            user_id="user1",
        )

        assert ok is True
        assert len(episodic_store._memories) == 1
        mem = episodic_store._memories[0]
        assert mem.tier == MemoryTier.OBSERVATION
        assert mem.weight == BRIDGE_MEMORY_WEIGHT
        assert mem.scope == MemoryScope.USER
        assert mem.org_id == "org1"
        assert mem.user_id == "user1"
        assert "session_summary:" in mem.source

    async def test_memory_weight_is_observation(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store)

        ok = await bridge.bridge_session(
            "org1/team1/user1:sess1",
            _make_messages(6),
            org_id="org1",
            user_id="user1",
        )

        assert ok is True
        mem = episodic_store._memories[0]
        assert mem.weight == pytest.approx(0.2)

    async def test_org_id_propagated(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store)

        await bridge.bridge_session(
            "myorg/myteam/myuser:s1",
            _make_messages(6),
            org_id="myorg",
            user_id="myuser",
        )

        mem = episodic_store._memories[0]
        assert mem.org_id == "myorg"


class TestBridgeSessionSkipsShort:
    """Sessions with fewer than MIN_MESSAGES_FOR_BRIDGE user messages are skipped."""

    async def test_skips_below_minimum(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store)

        # Only 2 user messages (below default threshold of 3)
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Bye"},
            {"role": "assistant", "content": "Goodbye"},
        ]
        ok = await bridge.bridge_session("s1", messages)

        assert ok is False
        assert len(episodic_store._memories) == 0

    async def test_skips_empty_session(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store)

        ok = await bridge.bridge_session("s1", [])
        assert ok is False


class TestBridgeWithLLM:
    """When an LLM is provided, it generates the summary."""

    async def test_llm_generates_summary(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        llm = FakeLLMClient()
        llm.set_simple_response("User prefers dark mode and Python 3.12.")
        bridge = SessionBridge(session_store, episodic_store, llm=llm)

        await bridge.bridge_session(
            "org1/team1/user1:sess1",
            _make_messages(6),
            org_id="org1",
            user_id="user1",
        )

        mem = episodic_store._memories[0]
        assert "dark mode" in mem.content
        assert len(llm.calls) == 1


class TestBridgeWithoutLLM:
    """Without an LLM, fallback summary extracts user messages."""

    async def test_fallback_summary(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store, llm=None)

        messages = [
            {"role": "user", "content": "I like Python"},
            {"role": "assistant", "content": "Great choice"},
            {"role": "user", "content": "And dark mode"},
            {"role": "assistant", "content": "Noted"},
            {"role": "user", "content": "Also vim keybindings"},
            {"role": "assistant", "content": "Sure"},
        ]
        await bridge.bridge_session("s1", messages, org_id="org1", user_id="u1")

        mem = episodic_store._memories[0]
        assert "Session summary:" in mem.content
        assert "Python" in mem.content


class TestSweepFindsExpired:
    """sweep() scans sessions, bridges expired ones, skips active ones."""

    async def test_sweep_bridges_expired(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        # Very short TTL for testing
        bridge = SessionBridge(session_store, episodic_store, session_ttl=1.0)

        # Add a session with enough messages
        sid = "org1/team1/user1:sess1"
        await session_store.append_messages(sid, _make_messages(8))

        # Backdate the timestamps to make them expired
        entries = session_store._sessions[sid]
        old_time = time.time() - 10.0  # 10 seconds ago, TTL is 1s
        session_store._sessions[sid] = [
            (seq, role, content, old_time) for seq, role, content, _ in entries
        ]

        bridged = await bridge.sweep()
        assert bridged == 1
        assert len(episodic_store._memories) == 1

    async def test_sweep_skips_non_expired(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store, session_ttl=86400.0)

        sid = "org1/team1/user1:sess1"
        await session_store.append_messages(sid, _make_messages(8))

        bridged = await bridge.sweep()
        assert bridged == 0
        assert len(episodic_store._memories) == 0


class TestAlreadyBridged:
    """Sessions that have already been bridged are not re-bridged."""

    async def test_no_double_bridge(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store, session_ttl=1.0)

        sid = "org1/team1/user1:sess1"
        await session_store.append_messages(sid, _make_messages(8))

        # Backdate to expire
        entries = session_store._sessions[sid]
        old_time = time.time() - 10.0
        session_store._sessions[sid] = [
            (seq, role, content, old_time) for seq, role, content, _ in entries
        ]

        # Sweep twice
        first = await bridge.sweep()
        second = await bridge.sweep()

        assert first == 1
        assert second == 0
        assert len(episodic_store._memories) == 1

    async def test_bridge_session_idempotent(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store)

        messages = _make_messages(6)
        first = await bridge.bridge_session("s1", messages, org_id="o1", user_id="u1")
        second = await bridge.bridge_session("s1", messages, org_id="o1", user_id="u1")

        assert first is True
        assert second is False
        assert len(episodic_store._memories) == 1


class TestSweepParsesSessionId:
    """sweep() correctly extracts org_id and user_id from session ID format."""

    async def test_extracts_identity_from_session_id(self) -> None:
        session_store = InMemorySessionStore()
        episodic_store = InMemoryEpisodicStore()
        bridge = SessionBridge(session_store, episodic_store, session_ttl=1.0)

        sid = "acme-corp/engineering/blake:daily-standup"
        await session_store.append_messages(sid, _make_messages(8))

        # Backdate
        entries = session_store._sessions[sid]
        old_time = time.time() - 10.0
        session_store._sessions[sid] = [
            (seq, role, content, old_time) for seq, role, content, _ in entries
        ]

        await bridge.sweep()

        mem = episodic_store._memories[0]
        assert mem.org_id == "acme-corp"
        assert mem.user_id == "blake"
