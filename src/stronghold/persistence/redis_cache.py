"""Redis-based cache for prompts, skills, and agent configs.

Provides simple key-value caching with TTL support.
"""

from __future__ import annotations

import logging
import json
from typing import Any

from stronghold.persistence.redis_pool import RedisPool

logger = logging.getLogger("stronghold.redis_cache")


class RedisCache:
    """Simple Redis-based cache with TTL."""

    def __init__(
        self,
        redis_pool: RedisPool,
        default_ttl: int = 300,
    ) -> None:
        """Initialize Redis cache.

        Args:
            redis_pool: Redis connection pool.
            default_ttl: Default TTL in seconds (5 minutes).
        """
        self.redis = redis_pool
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Any | None:
        """Get value from cache.

        Args:
            key: Cache key.

        Returns:
            Cached value, or None if not found.
        """
        value = await self.redis.get(key)

        if value is None:
            return None

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Set value in cache.

        Args:
            key: Cache key.
            value: Value to cache.
            ttl: TTL in seconds (uses default if None).
        """
        if isinstance(value, (str, int, float, bool)):
            str_value = str(value)
        else:
            str_value = json.dumps(value)

        await self.redis.set(key, str_value, ex=ttl or self.default_ttl)

    async def delete(self, key: str) -> None:
        """Delete value from cache.

        Args:
            key: Cache key.
        """
        await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Cache key.

        Returns:
            True if key exists.
        """
        return (await self.redis.exists(key)) > 0

    async def clear_prefix(self, prefix: str) -> int:
        """Delete all keys with given prefix.

        Args:
            prefix: Key prefix to match.

        Returns:
            Number of keys deleted.
        """
        # This would require Redis SCAN, which is more complex
        # For now, just log it
        logger.warning("clear_prefix not yet implemented for RedisCache: %s", prefix)
        return 0
