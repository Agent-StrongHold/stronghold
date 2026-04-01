"""Tests for InMemoryResponseCache — exact-match response caching with TTL.

Covers: cache miss, hit, expiration, task-type TTL, custom overrides,
deterministic keys, LRU eviction, invalidation, clear, and stats.
"""

from __future__ import annotations

import time

import pytest

from stronghold.cache.response_cache import (
    DEFAULT_FALLBACK_TTL,
    DEFAULT_TTL,
    CacheEntry,
    CacheStats,
    InMemoryResponseCache,
)

# ── Helpers ──────────────────────────────────────────────────────────

SAMPLE_MESSAGES = [{"role": "user", "content": "Hello, world!"}]
SAMPLE_MODEL = "test/small"
SAMPLE_TASK = "chat"
SAMPLE_RESPONSE: dict[str, object] = {
    "id": "resp-1",
    "choices": [{"message": {"role": "assistant", "content": "Hi!"}}],
}


def _make_cache(**kwargs: object) -> InMemoryResponseCache:
    return InMemoryResponseCache(**kwargs)  # type: ignore[arg-type]


# ── CacheEntry ───────────────────────────────────────────────────────


class TestCacheEntry:
    def test_not_expired_within_ttl(self) -> None:
        entry = CacheEntry(
            response={"x": 1}, created_at=time.time(), ttl=3600, task_type="chat"
        )
        assert not entry.is_expired

    def test_expired_after_ttl(self) -> None:
        entry = CacheEntry(
            response={"x": 1}, created_at=time.time() - 7200, ttl=3600, task_type="chat"
        )
        assert entry.is_expired


# ── CacheStats ───────────────────────────────────────────────────────


class TestCacheStats:
    def test_hit_rate_zero_when_empty(self) -> None:
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_calculation(self) -> None:
        stats = CacheStats(hits=3, misses=7)
        assert stats.hit_rate == pytest.approx(0.3)

    def test_hit_rate_perfect(self) -> None:
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == pytest.approx(1.0)


# ── Cache key ────────────────────────────────────────────────────────


class TestCacheKey:
    def test_deterministic(self) -> None:
        cache = _make_cache()
        k1 = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        k2 = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert k1 == k2

    def test_different_messages_different_keys(self) -> None:
        cache = _make_cache()
        k1 = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        k2 = cache.cache_key(
            [{"role": "user", "content": "Different"}], SAMPLE_MODEL, SAMPLE_TASK
        )
        assert k1 != k2

    def test_different_model_different_keys(self) -> None:
        cache = _make_cache()
        k1 = cache.cache_key(SAMPLE_MESSAGES, "model-a", SAMPLE_TASK)
        k2 = cache.cache_key(SAMPLE_MESSAGES, "model-b", SAMPLE_TASK)
        assert k1 != k2

    def test_different_task_type_different_keys(self) -> None:
        cache = _make_cache()
        k1 = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, "chat")
        k2 = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, "code")
        assert k1 != k2


# ── Miss / Hit ───────────────────────────────────────────────────────


class TestGetPut:
    def test_miss_returns_none(self) -> None:
        cache = _make_cache()
        assert cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK) is None

    def test_put_then_get(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        result = cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert result is not None
        assert result["id"] == "resp-1"

    def test_hit_increments_hit_count(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert cache._cache[key].hit_count == 2


# ── Expiration ───────────────────────────────────────────────────────


class TestExpiration:
    def test_expired_entry_returns_none(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        # Manually backdate the entry
        cache._cache[key].created_at = time.time() - 9999
        assert cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK) is None

    def test_expired_entry_removed_on_get(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        cache._cache[key].created_at = time.time() - 9999
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert key not in cache._cache


# ── Task-type TTL ────────────────────────────────────────────────────


class TestTaskTypeTTL:
    def test_creative_never_cached(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, "creative", dict(SAMPLE_RESPONSE))
        assert cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, "creative") is None

    def test_chat_uses_default_ttl(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, "chat", dict(SAMPLE_RESPONSE))
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, "chat")
        assert cache._cache[key].ttl == DEFAULT_TTL["chat"]

    def test_unknown_task_uses_fallback_ttl(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, "unknown_type", dict(SAMPLE_RESPONSE))
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, "unknown_type")
        assert cache._cache[key].ttl == DEFAULT_FALLBACK_TTL

    def test_custom_ttl_override(self) -> None:
        cache = _make_cache(ttl_overrides={"chat": 60})
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, "chat", dict(SAMPLE_RESPONSE))
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, "chat")
        assert cache._cache[key].ttl == 60


# ── LRU eviction ─────────────────────────────────────────────────────


class TestEviction:
    def test_max_entries_evicts_oldest(self) -> None:
        cache = _make_cache(max_entries=2)
        msgs_a = [{"role": "user", "content": "a"}]
        msgs_b = [{"role": "user", "content": "b"}]
        msgs_c = [{"role": "user", "content": "c"}]

        cache.put(msgs_a, SAMPLE_MODEL, SAMPLE_TASK, {"id": "a"})
        cache.put(msgs_b, SAMPLE_MODEL, SAMPLE_TASK, {"id": "b"})
        # This should evict 'a' (oldest)
        cache.put(msgs_c, SAMPLE_MODEL, SAMPLE_TASK, {"id": "c"})

        assert cache.get(msgs_a, SAMPLE_MODEL, SAMPLE_TASK) is None
        assert cache.get(msgs_b, SAMPLE_MODEL, SAMPLE_TASK) is not None
        assert cache.get(msgs_c, SAMPLE_MODEL, SAMPLE_TASK) is not None

    def test_eviction_increments_stats(self) -> None:
        cache = _make_cache(max_entries=1)
        msgs_a = [{"role": "user", "content": "a"}]
        msgs_b = [{"role": "user", "content": "b"}]

        cache.put(msgs_a, SAMPLE_MODEL, SAMPLE_TASK, {"id": "a"})
        cache.put(msgs_b, SAMPLE_MODEL, SAMPLE_TASK, {"id": "b"})
        assert cache.stats.evictions >= 1


# ── Invalidate / Clear ───────────────────────────────────────────────


class TestInvalidateAndClear:
    def test_invalidate_removes_entry(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        key = cache.cache_key(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert cache.invalidate(key) is True
        assert cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK) is None

    def test_invalidate_nonexistent_returns_false(self) -> None:
        cache = _make_cache()
        assert cache.invalidate("nonexistent-key") is False

    def test_clear_removes_all(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        cache.put(
            [{"role": "user", "content": "other"}],
            SAMPLE_MODEL,
            SAMPLE_TASK,
            {"id": "resp-2"},
        )
        cache.clear()
        assert len(cache._cache) == 0

    def test_clear_resets_entries_stat(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        cache.clear()
        assert cache.stats.entries == 0


# ── Stats tracking ───────────────────────────────────────────────────


class TestStats:
    def test_miss_increments_misses(self) -> None:
        cache = _make_cache()
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert cache.stats.misses == 1

    def test_hit_increments_hits(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        assert cache.stats.hits == 1

    def test_entries_count(self) -> None:
        cache = _make_cache()
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        assert cache.stats.entries == 1

    def test_stats_after_multiple_operations(self) -> None:
        cache = _make_cache()
        # 1 miss
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        # 1 put
        cache.put(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK, dict(SAMPLE_RESPONSE))
        # 2 hits
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)
        cache.get(SAMPLE_MESSAGES, SAMPLE_MODEL, SAMPLE_TASK)

        assert cache.stats.misses == 1
        assert cache.stats.hits == 2
        assert cache.stats.entries == 1
        assert cache.stats.hit_rate == pytest.approx(2 / 3)
