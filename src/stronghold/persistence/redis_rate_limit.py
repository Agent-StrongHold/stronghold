"""Redis-based rate limiter using sliding window.

Implements RateLimiter protocol using Redis sorted sets for distributed
rate limiting. Works across multiple instances.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from stronghold.protocols.rate_limit import RateLimiter
from stronghold.persistence.redis_pool import RedisPool

logger = logging.getLogger("stronghold.redis_rate_limit")


class RedisRateLimiter(RateLimiter):
    """Redis-based sliding window rate limiter.

    Tracks request timestamps in a sorted set with automatic cleanup of
    expired entries.
    """

    def __init__(
        self,
        redis_pool: RedisPool,
        requests: int = 10,
        window_seconds: int = 60,
    ) -> None:
        """Initialize Redis rate limiter.

        Args:
            redis_pool: Redis connection pool.
            requests: Maximum number of requests allowed.
            window_seconds: Time window in seconds.
        """
        self.redis = redis_pool
        self.requests = requests
        self.window = window_seconds

    async def check(self, key: str) -> tuple[bool, dict[str, str]]:
        """Check if request should be allowed.

        Uses sliding window: counts requests in the last `window_seconds`.

        Args:
            key: Unique identifier (user_id, API key, IP, etc).

        Returns:
            (allowed, headers) where headers contains X-RateLimit-* values.
        """
        redis_key = f"rate_limit:{key}"
        now = time.time()
        window_start = now - self.window

        # Remove old entries outside the window
        await self.redis.zremrangebyscore(redis_key, 0, window_start)

        # Count current requests
        count = await self.redis.zcard(redis_key)

        allowed = count < self.requests

        if allowed:
            # Add this request
            await self.redis.zadd(redis_key, {str(now): now})

        # Set expiration (cleanup)
        await self.redis.expire(redis_key, self.window)

        # Build response headers
        remaining = max(0, self.requests - count - (1 if allowed else 0))
        reset_time = int(now + self.window)

        headers = {
            "X-RateLimit-Limit": str(self.requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_time),
            "X-RateLimit-Used": str(count),
        }

        if not allowed:
            logger.debug("Rate limit exceeded: %s (count: %d)", key, count)
        else:
            logger.debug("Request allowed: %s (count: %d)", key, count + 1)

        return allowed, headers

    async def record(self, key: str) -> None:
        """Record a request against the key's rate limit.

        Args:
            key: Unique identifier.
        """
        redis_key = f"rate_limit:{key}"
        now = time.time()

        await self.redis.zadd(redis_key, {str(now): now})
        await self.redis.expire(redis_key, self.window)
