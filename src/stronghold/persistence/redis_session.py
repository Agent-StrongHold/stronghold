"""Redis-backed session store.

Implements SessionStore protocol using Redis for distributed session management.
Sessions are stored with TTL-based expiry (default 24 hours).
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.protocols.memory import SessionStore
from stronghold.persistence.redis_pool import RedisPool

logger = logging.getLogger("stronghold.redis_session")


class RedisSessionStore(SessionStore):
    """Redis-based session store with TTL expiry.

    Sessions expire after 24 hours by default.
    """

    def __init__(self, redis_pool: RedisPool, ttl_seconds: int = 86400) -> None:
        """Initialize Redis session store.

        Args:
            redis_pool: Redis connection pool.
            ttl_seconds: Time-to-live for sessions (default 24 hours).
        """
        self.redis = redis_pool
        self.ttl = ttl_seconds

    async def save(self, session_id: str, data: dict[str, Any]) -> None:
        """Save session data to Redis.

        Args:
            session_id: Unique session identifier.
            data: Session data (user_id, org_id, tokens, etc).
        """
        import json

        key = f"session:{session_id}"
        value = json.dumps(data)

        await self.redis.set(key, value, ex=self.ttl)
        logger.debug("Session saved: %s (TTL: %ds)", session_id, self.ttl)

    async def get(self, session_id: str) -> dict[str, Any] | None:
        """Get session data from Redis.

        Args:
            session_id: Unique session identifier.

        Returns:
            Session data if exists, None otherwise.
        """
        import json

        key = f"session:{session_id}"
        value = await self.redis.get(key)

        if value is None:
            logger.debug("Session not found: %s", session_id)
            return None

        try:
            data = json.loads(value)
            logger.debug("Session retrieved: %s", session_id)
            return data
        except json.JSONDecodeError as e:
            logger.error("Failed to decode session data: %s: %s", session_id, e)
            return None

    async def delete(self, session_id: str) -> bool:
        """Delete session from Redis.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if session was deleted, False if not found.
        """
        key = f"session:{session_id}"
        deleted = await self.redis.delete(key)

        if deleted:
            logger.debug("Session deleted: %s", session_id)

        return deleted > 0

    async def exists(self, session_id: str) -> bool:
        """Check if session exists.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if session exists.
        """
        key = f"session:{session_id}"
        return await self.redis.exists(key)

    async def refresh(self, session_id: str) -> bool:
        """Refresh session TTL.

        Args:
            session_id: Unique session identifier.

        Returns:
            True if session existed and was refreshed.
        """
        key = f"session:{session_id}"
        exists = await self.redis.exists(key)

        if exists > 0:
            await self.redis.expire(key, self.ttl)
            logger.debug("Session refreshed: %s", session_id)
            return True

        return False
