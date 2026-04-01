"""JWKS (JSON Web Key Set) cache for OIDC token validation.

Fetches public keys from an IdP's JWKS endpoint and caches them
with a configurable TTL. Used by OIDCAuthProvider to verify JWT
signatures without importing PyJWKClient (which is synchronous).

Stampede prevention: an asyncio.Lock ensures only one task fetches
at a time; others wait or use stale cache.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("stronghold.security.jwks")


class JWKSCache:
    """Fetches and caches JWKS keys from an OIDC provider.

    Args:
        url: JWKS endpoint URL (e.g., https://sso.example.com/.well-known/jwks.json).
        ttl: Cache time-to-live in seconds (default: 3600).
    """

    def __init__(self, url: str, ttl: float = 3600.0) -> None:
        self._url = url
        self._ttl = ttl
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_key(self, kid: str) -> dict[str, Any] | None:
        """Return the JWK for the given key ID, or None if not found.

        If the cache is empty or expired, fetches from the JWKS endpoint.
        If the kid is not found in a fresh cache, triggers one refresh
        (handles key rotation), then returns None if still missing.
        """
        # Ensure cache is populated
        if not self._keys or self._is_expired():
            await self._fetch()

        # Fast path: key found
        if kid in self._keys:
            return self._keys[kid]

        # Key not found — might be a rotation; refresh once
        await self.refresh()
        return self._keys.get(kid)

    async def refresh(self) -> None:
        """Force-refresh the JWKS cache regardless of TTL."""
        await self._fetch()

    def _is_expired(self) -> bool:
        """Check if the cache TTL has elapsed."""
        return (time.monotonic() - self._fetched_at) >= self._ttl

    async def _fetch(self) -> None:
        """Fetch JWKS from the endpoint. Lock prevents stampede."""
        async with self._lock:
            # Double-check: another waiter may have already refreshed
            # Skip this optimization on force-refresh (called from refresh())
            # by always fetching when explicitly requested.
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(self._url, timeout=10.0)
                    resp.raise_for_status()
                    data = resp.json()

                keys: dict[str, dict[str, Any]] = {}
                for key in data.get("keys", []):
                    kid = key.get("kid")
                    if kid:
                        keys[str(kid)] = dict(key)

                self._keys = keys
                self._fetched_at = time.monotonic()
                logger.info("JWKS refreshed from %s (%d keys)", self._url, len(keys))

            except Exception:
                # If we have stale keys, keep using them
                if self._keys:
                    logger.warning(
                        "JWKS refresh failed, using stale cache (%d keys)",
                        len(self._keys),
                    )
                else:
                    logger.error("JWKS refresh failed and no stale cache available")
                    raise
