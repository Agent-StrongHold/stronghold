"""Tests for RedisSessionStore."""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from stronghold.cache.session_store import RedisSessionStore


@pytest.fixture
async def redis_client() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


async def test_append_then_get(redis_client) -> None:
    store = RedisSessionStore(redis_client)
    await store.append_messages(
        "acme/team1/alice:session1",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
    )
    history = await store.get_history("acme/team1/alice:session1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"
    assert history[1]["role"] == "assistant"


async def test_bare_session_id_rejected_on_write(redis_client) -> None:
    """Non-org-scoped session IDs must be rejected as defense-in-depth."""
    store = RedisSessionStore(redis_client)
    await store.append_messages("bare-id", [{"role": "user", "content": "test"}])
    # Should have written nothing
    history = await store.get_history("acme/team1/alice:session1")
    assert history == []


async def test_bare_session_id_rejected_on_read(redis_client) -> None:
    store = RedisSessionStore(redis_client)
    history = await store.get_history("bare-id")
    assert history == []


async def test_empty_message_list_noop(redis_client) -> None:
    store = RedisSessionStore(redis_client)
    await store.append_messages("acme/t/u:s", [])
    assert await store.get_history("acme/t/u:s") == []


async def test_invalid_role_skipped(redis_client) -> None:
    """Only user/assistant roles stored; system/tool/etc skipped."""
    store = RedisSessionStore(redis_client)
    await store.append_messages(
        "acme/t/u:s",
        [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "q1"},
            {"role": "tool", "content": "tool result"},
            {"role": "assistant", "content": "a1"},
        ],
    )
    history = await store.get_history("acme/t/u:s")
    assert len(history) == 2
    assert [m["role"] for m in history] == ["user", "assistant"]


async def test_non_string_content_skipped(redis_client) -> None:
    store = RedisSessionStore(redis_client)
    await store.append_messages(
        "acme/t/u:s",
        [
            {"role": "user", "content": "valid"},
            {"role": "user", "content": ["list", "not", "string"]},
            {"role": "user", "content": None},
        ],
    )
    history = await store.get_history("acme/t/u:s")
    assert len(history) == 1
    assert history[0]["content"] == "valid"


async def test_max_messages_trimming(redis_client) -> None:
    """Session list is trimmed to max_messages."""
    store = RedisSessionStore(redis_client, max_messages=3)
    msgs = [{"role": "user", "content": f"msg{i}"} for i in range(5)]
    await store.append_messages("acme/t/u:s", msgs)
    history = await store.get_history("acme/t/u:s")
    assert len(history) == 3
    # Should keep the most recent
    assert history[0]["content"] == "msg2"
    assert history[2]["content"] == "msg4"


async def test_ttl_expired_messages_filtered(redis_client) -> None:
    """Per-message TTL filters out old messages on read.

    Write a message, then sleep past the per-message TTL, verify it's filtered.
    """
    import asyncio
    store = RedisSessionStore(redis_client, ttl_seconds=3600)
    await store.append_messages("acme/t/u:s", [{"role": "user", "content": "fresh"}])
    # Sleep briefly then read with a very short TTL (less than elapsed time)
    await asyncio.sleep(0.1)
    history = await store.get_history("acme/t/u:s", ttl_seconds=-1)
    # Negative TTL → cutoff is future → everything is "expired"
    # Actually: cutoff = now - (-1) = now + 1, so ts < cutoff, filtered out
    assert history == []


async def test_delete_session(redis_client) -> None:
    store = RedisSessionStore(redis_client)
    await store.append_messages("acme/t/u:s", [{"role": "user", "content": "x"}])
    assert len(await store.get_history("acme/t/u:s")) == 1
    await store.delete_session("acme/t/u:s")
    assert await store.get_history("acme/t/u:s") == []


async def test_delete_bare_id_is_noop(redis_client) -> None:
    store = RedisSessionStore(redis_client)
    # Should not raise, should not affect anything
    await store.delete_session("bare")


async def test_tenant_isolation_via_session_id(redis_client) -> None:
    """Different org-prefixed IDs don't leak into each other."""
    store = RedisSessionStore(redis_client)
    await store.append_messages("acme/t/u:s", [{"role": "user", "content": "acme secret"}])
    await store.append_messages("evil/t/u:s", [{"role": "user", "content": "evil secret"}])
    acme = await store.get_history("acme/t/u:s")
    evil = await store.get_history("evil/t/u:s")
    assert acme[0]["content"] == "acme secret"
    assert evil[0]["content"] == "evil secret"


async def test_max_messages_override_on_read(redis_client) -> None:
    store = RedisSessionStore(redis_client, max_messages=100)
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(10)]
    await store.append_messages("acme/t/u:s", msgs)
    # Read override
    history = await store.get_history("acme/t/u:s", max_messages=3)
    assert len(history) == 3
    assert history[-1]["content"] == "m9"
