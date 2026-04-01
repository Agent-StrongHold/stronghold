"""Comprehensive tests for InMemorySessionStore, build_session_id, and validation helpers."""

from __future__ import annotations

import pytest

from stronghold.sessions.store import (
    InMemorySessionStore,
    build_session_id,
    validate_and_build_session_id,
    validate_session_ownership,
)
from stronghold.types.session import SessionConfig

# ── build_session_id ────────────────────────────────────────────────────


class TestBuildSessionId:
    """Unit tests for build_session_id format."""

    def test_format_includes_all_components(self) -> None:
        sid = build_session_id("org1", "team1", "user1", "chat")
        assert sid == "org1/team1/user1:chat"

    def test_components_with_hyphens(self) -> None:
        sid = build_session_id("acme-corp", "eng-team", "u-42", "my-session")
        assert sid == "acme-corp/eng-team/u-42:my-session"

    def test_different_orgs_produce_different_ids(self) -> None:
        a = build_session_id("org-a", "t", "u", "s")
        b = build_session_id("org-b", "t", "u", "s")
        assert a != b

    def test_different_sessions_same_user_produce_different_ids(self) -> None:
        a = build_session_id("org", "team", "user", "session-1")
        b = build_session_id("org", "team", "user", "session-2")
        assert a != b


# ── validate_session_ownership ──────────────────────────────────────────


class TestValidateSessionOwnership:
    """Ownership validation for org-scoped session IDs."""

    def test_valid_ownership(self) -> None:
        sid = build_session_id("org1", "team1", "user1", "chat")
        assert validate_session_ownership(sid, "org1") is True

    def test_wrong_org_rejected(self) -> None:
        sid = build_session_id("org1", "team1", "user1", "chat")
        assert validate_session_ownership(sid, "org2") is False

    def test_empty_org_always_rejected(self) -> None:
        sid = build_session_id("org1", "team1", "user1", "chat")
        assert validate_session_ownership(sid, "") is False

    def test_prefix_attack_rejected(self) -> None:
        """org1-evil should not match org1."""
        sid = "org1-evil/team/user:chat"
        assert validate_session_ownership(sid, "org1") is False


# ── validate_and_build_session_id ───────────────────────────────────────


class TestValidateAndBuildSessionId:
    """Tests for the combined validate-or-build helper."""

    def test_none_returns_none(self) -> None:
        result = validate_and_build_session_id(None, "org1")
        assert result is None

    def test_bare_name_auto_scoped(self) -> None:
        result = validate_and_build_session_id("my-chat", "org1", "team1", "user1")
        assert result == "org1/team1/user1:my-chat"

    def test_bare_name_missing_team_user_uses_placeholder(self) -> None:
        result = validate_and_build_session_id("my-chat", "org1")
        assert result == "org1/_/_:my-chat"

    def test_already_scoped_valid_passes_through(self) -> None:
        scoped = "org1/team1/user1:chat"
        result = validate_and_build_session_id(scoped, "org1")
        assert result == scoped

    def test_already_scoped_wrong_org_raises(self) -> None:
        scoped = "org1/team1/user1:chat"
        with pytest.raises(ValueError, match="does not belong"):
            validate_and_build_session_id(scoped, "org2")

    def test_invalid_characters_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid session ID format"):
            validate_and_build_session_id("session with spaces", "org1")

    def test_special_chars_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid session ID format"):
            validate_and_build_session_id("session;drop table", "org1")


# ── append_messages ─────────────────────────────────────────────────────


class TestAppendMessages:
    """Tests for message appending behaviour."""

    async def test_append_single_message(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0] == {"role": "user", "content": "hello"}

    async def test_append_user_and_assistant(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": "question"},
                {"role": "assistant", "content": "answer"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    async def test_system_role_filtered(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "system", "content": "you are helpful"},
                {"role": "user", "content": "hi"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["role"] == "user"

    async def test_tool_role_filtered(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "tool", "content": "result"},
                {"role": "user", "content": "thanks"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 1

    async def test_non_string_content_filtered(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": 42},  # type: ignore[dict-item]
                {"role": "user", "content": "valid"},
            ],
        )
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["content"] == "valid"

    async def test_empty_list_no_effect(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [])
        history = await store.get_history("s1")
        assert history == []

    async def test_missing_role_key_filtered(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"content": "no role"},
                {"role": "user", "content": "with role"},
            ],
        )
        history = await store.get_history("s1")
        # Missing role defaults to "" which is not in ("user", "assistant")
        assert len(history) == 1

    async def test_multiple_appends_accumulate(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "a"}])
        await store.append_messages("s1", [{"role": "assistant", "content": "b"}])
        await store.append_messages("s1", [{"role": "user", "content": "c"}])
        history = await store.get_history("s1")
        assert len(history) == 3
        assert [m["content"] for m in history] == ["a", "b", "c"]


# ── get_history ─────────────────────────────────────────────────────────


class TestGetHistory:
    """Tests for history retrieval with limits and TTL."""

    async def test_nonexistent_session_returns_empty(self) -> None:
        store = InMemorySessionStore()
        history = await store.get_history("nonexistent")
        assert history == []

    async def test_max_messages_override(self) -> None:
        store = InMemorySessionStore()
        for i in range(30):
            await store.append_messages("s1", [{"role": "user", "content": f"msg-{i}"}])
        history = await store.get_history("s1", max_messages=3)
        assert len(history) == 3
        # Most recent 3
        assert history[0]["content"] == "msg-27"
        assert history[2]["content"] == "msg-29"

    async def test_config_max_messages_enforced(self) -> None:
        config = SessionConfig(max_messages=5, ttl_seconds=86400)
        store = InMemorySessionStore(config=config)
        for i in range(20):
            await store.append_messages("s1", [{"role": "user", "content": f"msg-{i}"}])
        history = await store.get_history("s1")
        assert len(history) == 5
        # Keeps the most recent
        assert history[-1]["content"] == "msg-19"
        assert history[0]["content"] == "msg-15"

    async def test_ttl_filtering(self) -> None:
        config = SessionConfig(ttl_seconds=10)
        store = InMemorySessionStore(config=config)
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        # Manually age the stored message beyond TTL
        entries = store._sessions["s1"]
        store._sessions["s1"] = [(e[0], e[1], e[2], e[3] - 20) for e in entries]
        # Add a fresh one
        await store.append_messages("s1", [{"role": "user", "content": "new"}])
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["content"] == "new"

    async def test_returns_role_and_content_only(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "test"}])
        history = await store.get_history("s1")
        assert set(history[0].keys()) == {"role", "content"}


# ── sequence numbers ────────────────────────────────────────────────────


class TestSequenceNumbers:
    """Sequence numbers ensure correct ordering."""

    async def test_sequence_numbers_monotonically_increase(self) -> None:
        store = InMemorySessionStore()
        for i in range(10):
            await store.append_messages("s1", [{"role": "user", "content": f"m{i}"}])
        entries = store._sessions["s1"]
        seqs = [e[0] for e in entries]
        assert seqs == list(range(10))

    async def test_sequence_numbers_independent_per_session(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "a"}])
        await store.append_messages("s2", [{"role": "user", "content": "b"}])
        # Both sessions start their sequence at 0
        assert store._sessions["s1"][0][0] == 0
        assert store._sessions["s2"][0][0] == 0

    async def test_batch_append_assigns_consecutive_sequences(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(
            "s1",
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ],
        )
        entries = store._sessions["s1"]
        seqs = [e[0] for e in entries]
        assert seqs == [0, 1, 2]


# ── delete_session ──────────────────────────────────────────────────────


class TestDeleteSession:
    """Delete clears both history and sequence counter."""

    async def test_delete_clears_history(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        await store.delete_session("s1")
        assert await store.get_history("s1") == []

    async def test_delete_resets_sequence_counter(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "hello"}])
        assert store._next_seq["s1"] == 1
        await store.delete_session("s1")
        # After deletion, the counter entry is removed
        assert "s1" not in store._next_seq

    async def test_delete_nonexistent_is_safe(self) -> None:
        store = InMemorySessionStore()
        await store.delete_session("ghost")  # no error

    async def test_delete_then_reuse_starts_fresh(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        await store.delete_session("s1")
        await store.append_messages("s1", [{"role": "user", "content": "new"}])
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["content"] == "new"
        # Sequence restarts at 0
        assert store._sessions["s1"][0][0] == 0

    async def test_delete_does_not_affect_other_sessions(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages("s1", [{"role": "user", "content": "keep"}])
        await store.append_messages("s2", [{"role": "user", "content": "remove"}])
        await store.delete_session("s2")
        assert len(await store.get_history("s1")) == 1
        assert len(await store.get_history("s2")) == 0


# ── org scoping (via build_session_id) ──────────────────────────────────


class TestOrgScopedIsolation:
    """Org-scoped session IDs keep tenants isolated in the store."""

    async def test_different_orgs_isolated(self) -> None:
        store = InMemorySessionStore()
        sid_a = build_session_id("orgA", "team", "user", "chat")
        sid_b = build_session_id("orgB", "team", "user", "chat")
        await store.append_messages(sid_a, [{"role": "user", "content": "from A"}])
        await store.append_messages(sid_b, [{"role": "user", "content": "from B"}])
        ha = await store.get_history(sid_a)
        hb = await store.get_history(sid_b)
        assert len(ha) == 1
        assert len(hb) == 1
        assert ha[0]["content"] == "from A"
        assert hb[0]["content"] == "from B"

    async def test_same_org_different_users_isolated(self) -> None:
        store = InMemorySessionStore()
        sid_u1 = build_session_id("org", "team", "user1", "chat")
        sid_u2 = build_session_id("org", "team", "user2", "chat")
        await store.append_messages(sid_u1, [{"role": "user", "content": "user1 msg"}])
        await store.append_messages(sid_u2, [{"role": "user", "content": "user2 msg"}])
        h1 = await store.get_history(sid_u1)
        h2 = await store.get_history(sid_u2)
        assert h1[0]["content"] == "user1 msg"
        assert h2[0]["content"] == "user2 msg"

    async def test_delete_org_session_does_not_leak(self) -> None:
        store = InMemorySessionStore()
        sid_a = build_session_id("orgA", "team", "user", "chat")
        sid_b = build_session_id("orgB", "team", "user", "chat")
        await store.append_messages(sid_a, [{"role": "user", "content": "A data"}])
        await store.append_messages(sid_b, [{"role": "user", "content": "B data"}])
        await store.delete_session(sid_a)
        assert await store.get_history(sid_a) == []
        assert len(await store.get_history(sid_b)) == 1


# ── message ordering ───────────────────────────────────────────────────


class TestMessageOrdering:
    """Messages are returned in insertion order."""

    async def test_interleaved_user_assistant_order(self) -> None:
        store = InMemorySessionStore()
        conversation = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        await store.append_messages("s1", conversation)
        history = await store.get_history("s1")
        assert [m["content"] for m in history] == ["q1", "a1", "q2", "a2"]

    async def test_order_preserved_across_multiple_appends(self) -> None:
        store = InMemorySessionStore()
        for i in range(15):
            await store.append_messages("s1", [{"role": "user", "content": f"step-{i}"}])
        history = await store.get_history("s1")
        assert [m["content"] for m in history] == [f"step-{i}" for i in range(15)]


# ── max_messages edge cases ─────────────────────────────────────────────


class TestMaxMessagesEdgeCases:
    """Edge cases around the max_messages window."""

    async def test_exactly_at_limit(self) -> None:
        config = SessionConfig(max_messages=5, ttl_seconds=86400)
        store = InMemorySessionStore(config=config)
        for i in range(5):
            await store.append_messages("s1", [{"role": "user", "content": f"m{i}"}])
        history = await store.get_history("s1")
        assert len(history) == 5

    async def test_one_over_limit_drops_oldest(self) -> None:
        config = SessionConfig(max_messages=3, ttl_seconds=86400)
        store = InMemorySessionStore(config=config)
        for i in range(4):
            await store.append_messages("s1", [{"role": "user", "content": f"m{i}"}])
        history = await store.get_history("s1")
        assert len(history) == 3
        assert history[0]["content"] == "m1"
        assert history[2]["content"] == "m3"

    async def test_max_messages_one(self) -> None:
        config = SessionConfig(max_messages=1, ttl_seconds=86400)
        store = InMemorySessionStore(config=config)
        await store.append_messages("s1", [{"role": "user", "content": "first"}])
        await store.append_messages("s1", [{"role": "user", "content": "second"}])
        history = await store.get_history("s1")
        assert len(history) == 1
        assert history[0]["content"] == "second"

    async def test_override_max_larger_than_config(self) -> None:
        config = SessionConfig(max_messages=3, ttl_seconds=86400)
        store = InMemorySessionStore(config=config)
        for i in range(10):
            await store.append_messages("s1", [{"role": "user", "content": f"m{i}"}])
        history = await store.get_history("s1", max_messages=8)
        assert len(history) == 8
        assert history[0]["content"] == "m2"
        assert history[-1]["content"] == "m9"


# ── write-time TTL pruning ──────────────────────────────────────────────


class TestWriteTimePruning:
    """append_messages prunes expired entries on write."""

    async def test_expired_entries_pruned_on_write(self) -> None:
        config = SessionConfig(ttl_seconds=10)
        store = InMemorySessionStore(config=config)
        await store.append_messages("s1", [{"role": "user", "content": "old"}])
        # Age existing message beyond TTL
        entries = store._sessions["s1"]
        store._sessions["s1"] = [(e[0], e[1], e[2], e[3] - 20) for e in entries]
        # This write triggers pruning
        await store.append_messages("s1", [{"role": "user", "content": "new"}])
        # The old message should be pruned, only new remains in internal storage
        assert len(store._sessions["s1"]) == 1
        assert store._sessions["s1"][0][2] == "new"
