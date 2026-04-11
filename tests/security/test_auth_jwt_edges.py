"""Additional JWTAuthProvider edge-case tests for coverage."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from stronghold.security.auth_jwt import JWTAuthProvider
from stronghold.types.auth import IdentityKind


def _make_provider(**overrides):
    defaults = {
        "jwks_url": "https://auth.example.com/.well-known/jwks.json",
        "issuer": "https://auth.example.com",
        "audience": "stronghold",
    }
    defaults.update(overrides)
    return JWTAuthProvider(**defaults)


async def test_service_account_kind_detected() -> None:
    """Valid service_account kind detection."""
    provider = _make_provider()

    def fake_decode(token: str) -> dict:
        return {
            "sub": "sa-1",
            "org_id": "acme",
            "kind": "service_account",
            "roles": ["service"],
        }

    provider._jwt_decode = fake_decode  # type: ignore[method-assign]
    auth = await provider.authenticate("Bearer token")
    assert auth.kind == IdentityKind.SERVICE_ACCOUNT


async def test_default_kind_is_user() -> None:
    provider = _make_provider()

    def fake_decode(token: str) -> dict:
        return {"sub": "alice", "org_id": "acme", "roles": ["user"]}

    provider._jwt_decode = fake_decode  # type: ignore[method-assign]
    auth = await provider.authenticate("Bearer token")
    assert auth.kind == IdentityKind.USER


async def test_missing_sub_raises() -> None:
    """Token without 'sub' claim is rejected."""
    provider = _make_provider()

    def fake_decode(token: str) -> dict:
        return {"org_id": "acme"}

    provider._jwt_decode = fake_decode  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="sub"):
        await provider.authenticate("Bearer token")


async def test_require_org_missing_raises() -> None:
    provider = _make_provider(require_org=True)

    def fake_decode(token: str) -> dict:
        return {"sub": "alice"}

    provider._jwt_decode = fake_decode  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="organization"):
        await provider.authenticate("Bearer token")


async def test_jwks_cache_fast_path() -> None:
    """Second call within TTL hits the fast path (no lock)."""
    provider = _make_provider()
    fake_client = MagicMock()
    provider._jwks_cache = fake_client
    provider._jwks_cache_at = 999999  # far in the future

    import stronghold.security.auth_jwt as mod
    with patch.object(mod.time, "monotonic", return_value=999999):
        result = await provider._get_jwks_client(MagicMock(), MagicMock())
        assert result is fake_client


async def test_jwks_cache_stale_under_contention() -> None:
    """When lock is held and cache is stale, return stale cache."""
    provider = _make_provider(jwks_cache_ttl=0)  # always stale
    fake_cache = MagicMock()
    provider._jwks_cache = fake_cache

    # Hold the lock externally to simulate contention
    async def holder():
        async with provider._cache_lock:
            await asyncio.sleep(0.1)

    holder_task = asyncio.create_task(holder())
    await asyncio.sleep(0.01)  # let holder grab the lock

    # Now _get_jwks_client should see lock held + stale cache → return stale
    fake_client_cls = MagicMock()
    result = await provider._get_jwks_client(MagicMock(), fake_client_cls)
    assert result is fake_cache
    await holder_task


async def test_jwks_no_cache_lock_held_waits() -> None:
    """When lock is held and no cache exists, waits for the lock."""
    provider = _make_provider()
    provider._jwks_cache = None  # no cache at all

    async def holder():
        async with provider._cache_lock:
            await asyncio.sleep(0.05)

    holder_task = asyncio.create_task(holder())
    await asyncio.sleep(0.01)

    fake_client_cls = MagicMock(return_value="fresh-client")
    result = await provider._get_jwks_client(MagicMock(), fake_client_cls)
    assert result == "fresh-client"
    await holder_task


async def test_jwks_double_check_fresh_after_lock() -> None:
    """Double-check path: cache becomes fresh between first check and lock acquire."""
    provider = _make_provider(jwks_cache_ttl=3600)
    # No cache initially, so we pass fast-path
    provider._jwks_cache = None

    fake_client_cls = MagicMock(return_value="client-v1")
    result = await provider._get_jwks_client(MagicMock(), fake_client_cls)
    assert result == "client-v1"
    # Second call should hit the fast path
    result2 = await provider._get_jwks_client(MagicMock(), fake_client_cls)
    assert result2 == "client-v1"


async def test_extract_nested_empty_path() -> None:
    provider = _make_provider()
    assert provider._extract_nested({"a": 1}, "") is None


async def test_jwks_refresh_fails_stale_cache_returned() -> None:
    """If JWKS refresh raises and stale cache exists, return stale."""
    provider = _make_provider(jwks_cache_ttl=0)  # always stale
    provider._jwks_cache = "stale-client"
    provider._jwks_cache_at = 0

    fake_client_cls = MagicMock(side_effect=RuntimeError("network down"))
    result = await provider._get_jwks_client(MagicMock(), fake_client_cls)
    assert result == "stale-client"


async def test_jwks_refresh_fails_no_cache_raises() -> None:
    """If JWKS refresh raises and no cache, raise."""
    provider = _make_provider()
    provider._jwks_cache = None

    fake_client_cls = MagicMock(side_effect=RuntimeError("network down"))
    with pytest.raises(RuntimeError, match="network down"):
        await provider._get_jwks_client(MagicMock(), fake_client_cls)


async def test_decode_token_without_injection() -> None:
    """If _jwt_decode is None, tries to use real PyJWT — will fail in test env
    unless we mock properly. Verifies the import path runs.
    """
    provider = _make_provider()
    # Leave _jwt_decode None to hit the PyJWT import path
    # Mock the jwks_client to raise
    async def fake_get(*args):
        c = MagicMock()
        c.get_signing_key_from_jwt = MagicMock(side_effect=RuntimeError("jwks fail"))
        return c
    provider._get_jwks_client = fake_get  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="JWT validation failed"):
        await provider._decode_token("bogus-token")
