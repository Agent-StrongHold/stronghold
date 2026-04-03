"""Redis client wrapper for Stronghold.

Provides async Redis client with authentication support.
Used by session store, rate limiter, and cache.
"""

from __future__ import annotations

import logging
from typing import Any

import redis.asyncio as redis

logger = logging.getLogger("stronghold.redis")


class RedisPool:
    """Redis connection pool manager."""

    def __init__(self, url: str, max_connections: int = 50) -> None:
        """Initialize Redis pool.

        Args:
            url: Redis connection URL (redis://:password@host:port)
            max_connections: Maximum number of connections in pool
        """
        self.url = url
        self.max_connections = max_connections
        self._pool: redis.ConnectionPool | None = None

    async def get_client(self) -> redis.Redis:
        """Get a Redis client from the pool.

        Returns:
            Redis client instance.
        """
        if self._pool is None:
            self._pool = redis.ConnectionPool.from_url(
                self.url,
                max_connections=self.max_connections,
                decode_responses=True,
            )
            logger.info("Redis connection pool created: %s", self.url)

        return redis.Redis(connection_pool=self._pool)

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
            logger.info("Redis connection pool closed")

    async def ping(self) -> bool:
        """Check if Redis is responsive.

        Returns:
            True if Redis responds to PING, False otherwise.
        """
        client = await self.get_client()
        try:
            result = await client.ping()
            return result is True or result == b"PONG" or result == "PONG"
        except Exception as e:
            logger.error("Redis ping failed: %s", e)
            return False

    async def get(self, key: str) -> str | None:
        """Get a value from Redis.

        Args:
            key: Redis key.

        Returns:
            Value if key exists, None otherwise.
        """
        client = await self.get_client()
        return await client.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Set a value in Redis.

        Args:
            key: Redis key.
            value: Value to store.
            ex: Expiration time in seconds.
        """
        client = await self.get_client()
        if ex is not None:
            await client.setex(key, ex, value)
        else:
            await client.set(key, value)

    async def delete(self, key: str) -> int:
        """Delete a key from Redis.

        Args:
            key: Redis key.

        Returns:
            Number of keys deleted (0 or 1).
        """
        client = await self.get_client()
        return await client.delete(key)

    async def exists(self, key: str) -> int:
        """Check if a key exists.

        Args:
            key: Redis key.

        Returns:
            1 if key exists, 0 otherwise.
        """
        client = await self.get_client()
        return await client.exists(key)

    async def ttl(self, key: str) -> int:
        """Get time-to-live for a key.

        Args:
            key: Redis key.

        Returns:
            TTL in seconds, or -1 if key exists without expiration,
            or -2 if key does not exist.
        """
        client = await self.get_client()
        return await client.ttl(key)

    async def incr(self, key: str) -> int:
        """Increment a key value.

        Args:
            key: Redis key.

        Returns:
            New value after increment.
        """
        client = await self.get_client()
        return await client.incr(key)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on a key.

        Args:
            key: Redis key.
            seconds: TTL in seconds.

        Returns:
            True if successful.
        """
        client = await self.get_client()
        result = await client.expire(key, seconds)
        return result is True or result > 0

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        """Add members to sorted set.

        Args:
            key: Sorted set key.
            mapping: Member -> score mapping.

        Returns:
            Number of members added.
        """
        client = await self.get_client()
        return await client.zadd(key, mapping)

    async def zcard(self, key: str) -> int:
        """Get number of members in sorted set.

        Args:
            key: Sorted set key.

        Returns:
            Number of members.
        """
        client = await self.get_client()
        return await client.zcard(key)

    async def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> int:
        """Remove members in sorted set by score range.

        Args:
            key: Sorted set key.
            min_score: Minimum score.
            max_score: Maximum score.

        Returns:
            Number of members removed.
        """
        client = await self.get_client()
        return await client.zremrangebyscore(key, min_score, max_score)

    async def zrangebyscore(self, key: str, min_score: float, max_score: float) -> list[str]:
        """Get members in sorted set by score range.

        Args:
            key: Sorted set key.
            min_score: Minimum score.
            max_score: Maximum score.

        Returns:
            List of member values.
        """
        client = await self.get_client()
        return await client.zrangebyscore(key, min_score, max_score)
