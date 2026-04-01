"""Response cache for LLM completions.

Exact-match cache keyed on message content + model + task_type.
Task-type-aware TTL: chat=3600s, real-time=300s, creative=0 (no cache).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("stronghold.cache.response")

# Default TTL per task_type (seconds). 0 = never cache.
DEFAULT_TTL: dict[str, int] = {
    "chat": 3600,  # 1 hour
    "code": 1800,  # 30 min
    "search": 600,  # 10 min
    "smart_home": 300,  # 5 min (real-time)
    "trading": 60,  # 1 min (real-time)
    "creative": 0,  # never cache
}
DEFAULT_FALLBACK_TTL = 1800  # 30 min for unknown task types


@dataclass
class CacheEntry:
    """A single cached response with metadata."""

    response: dict[str, Any]
    created_at: float
    ttl: int
    task_type: str
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl


@dataclass
class CacheStats:
    """Aggregate cache statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class InMemoryResponseCache:
    """In-memory response cache with TTL and task-type awareness.

    Keys are SHA-256 hashes of (messages, model, task_type). Each task
    type has its own TTL (e.g. creative=0 means never cache). When the
    cache reaches ``max_entries``, the least-recently-used entry is evicted.
    """

    def __init__(
        self,
        ttl_overrides: dict[str, int] | None = None,
        max_entries: int = 1000,
    ) -> None:
        self._cache: dict[str, CacheEntry] = {}
        self._ttls = {**DEFAULT_TTL, **(ttl_overrides or {})}
        self._max_entries = max_entries
        self._stats = CacheStats()
        # Insertion-order list for LRU tracking (oldest first).
        self._access_order: list[str] = []

    def cache_key(
        self,
        messages: list[dict[str, Any]],
        model: str,
        task_type: str,
    ) -> str:
        """Generate deterministic cache key from request parameters."""
        content = json.dumps(
            {"messages": messages, "model": model, "task_type": task_type},
            sort_keys=True,
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def get(
        self,
        messages: list[dict[str, Any]],
        model: str,
        task_type: str,
    ) -> dict[str, Any] | None:
        """Get cached response. Returns None on miss or expired entry."""
        key = self.cache_key(messages, model, task_type)
        entry = self._cache.get(key)

        if entry is None:
            self._stats.misses += 1
            return None

        if entry.is_expired:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self._stats.entries = len(self._cache)
            self._stats.misses += 1
            self._stats.evictions += 1
            return None

        entry.hit_count += 1
        self._stats.hits += 1

        # Move to end of access order (most recently used).
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        return entry.response

    def put(
        self,
        messages: list[dict[str, Any]],
        model: str,
        task_type: str,
        response: dict[str, Any],
    ) -> None:
        """Cache a response. Respects task_type TTL. No-op if TTL=0."""
        ttl = self._ttls.get(task_type, DEFAULT_FALLBACK_TTL)
        if ttl == 0:
            return

        key = self.cache_key(messages, model, task_type)

        # Evict expired entries before checking capacity.
        self._evict_expired()

        # Evict LRU if at capacity (and not replacing existing key).
        if key not in self._cache and len(self._cache) >= self._max_entries:
            self._evict_lru()

        self._cache[key] = CacheEntry(
            response=response,
            created_at=time.time(),
            ttl=ttl,
            task_type=task_type,
        )

        # Track access order.
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

        self._stats.entries = len(self._cache)

    def invalidate(self, key: str) -> bool:
        """Remove a specific entry. Returns True if it existed."""
        if key in self._cache:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self._stats.entries = len(self._cache)
            return True
        return False

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()
        self._access_order.clear()
        self._stats.entries = 0

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def _evict_expired(self) -> None:
        """Remove expired entries."""
        expired_keys = [k for k, v in self._cache.items() if v.is_expired]
        for key in expired_keys:
            del self._cache[key]
            if key in self._access_order:
                self._access_order.remove(key)
            self._stats.evictions += 1
        self._stats.entries = len(self._cache)

    def _evict_lru(self) -> None:
        """Evict least-recently-used entry when at capacity."""
        if not self._access_order:
            return
        lru_key = self._access_order.pop(0)
        if lru_key in self._cache:
            del self._cache[lru_key]
            self._stats.evictions += 1
            self._stats.entries = len(self._cache)
