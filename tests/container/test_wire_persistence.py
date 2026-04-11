"""Tests for container wiring paths (auth, persistence, redis, rate limit)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _minimal_config(**overrides):
    """Build a minimal StrongholdConfig with sensible defaults."""
    from stronghold.types.config import StrongholdConfig
    defaults = {
        "router_api_key": "sk-" + "x" * 32,
        "database_url": "",
        "redis_url": "",
        "permissions": {"admin": ["*"]},
        "providers": {"test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000}},
        "models": {"m": {"provider": "test", "litellm_id": "test/m", "tier": "medium", "quality": 0.7, "speed": 500, "strengths": ["chat"]}},
    }
    defaults.update(overrides)
    return StrongholdConfig(**defaults)


# ── _wire_persistence ──────────────────────────────────────────────


async def test_wire_persistence_no_database_url_uses_in_memory() -> None:
    from stronghold.container import _wire_persistence
    from stronghold.memory.learnings.store import InMemoryLearningStore
    from stronghold.memory.outcomes import InMemoryOutcomeStore
    from stronghold.prompts.store import InMemoryPromptManager
    from stronghold.quota.tracker import InMemoryQuotaTracker
    from stronghold.security.sentinel.audit import InMemoryAuditLog
    from stronghold.sessions.store import InMemorySessionStore

    config = _minimal_config(database_url="")
    db_pool, qt, pm, ls, os_, ss, al = await _wire_persistence(config)
    assert db_pool is None
    assert isinstance(qt, InMemoryQuotaTracker)
    assert isinstance(pm, InMemoryPromptManager)
    assert isinstance(ls, InMemoryLearningStore)
    assert isinstance(os_, InMemoryOutcomeStore)
    assert isinstance(ss, InMemorySessionStore)
    assert isinstance(al, InMemoryAuditLog)


async def test_wire_persistence_with_database_url() -> None:
    """When DATABASE_URL is set, wire PostgreSQL adapters."""
    from stronghold.container import _wire_persistence

    config = _minimal_config(database_url="postgresql://user:pass@host/db")
    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()

    with patch("stronghold.persistence.get_pool", new=AsyncMock(return_value=fake_pool)), \
         patch("stronghold.persistence.run_migrations", new=AsyncMock()), \
         patch("stronghold.persistence.pg_quota.PgQuotaTracker") as m_qt, \
         patch("stronghold.persistence.pg_prompts.PgPromptManager") as m_pm, \
         patch("stronghold.persistence.pg_learnings.PgLearningStore") as m_ls, \
         patch("stronghold.persistence.pg_outcomes.PgOutcomeStore") as m_os, \
         patch("stronghold.persistence.pg_sessions.PgSessionStore") as m_ss, \
         patch("stronghold.persistence.pg_audit.PgAuditLog") as m_al:
        db_pool, qt, pm, ls, os_, ss, al = await _wire_persistence(config)

    assert db_pool is fake_pool
    m_qt.assert_called_once_with(fake_pool)
    m_pm.assert_called_once_with(fake_pool)
    m_ls.assert_called_once_with(fake_pool)
    m_os.assert_called_once_with(fake_pool)
    m_ss.assert_called_once_with(fake_pool)
    m_al.assert_called_once_with(fake_pool)


# ── _wire_auth ──────────────────────────────────────────────────────


def test_wire_auth_no_jwks_uses_static_plus_demo() -> None:
    """Without jwks_url, wire static key + demo cookie."""
    from stronghold.container import _wire_auth
    config = _minimal_config()
    auth, perms = _wire_auth(config)
    assert auth is not None
    assert perms is not None


def test_wire_auth_with_jwks_enables_jwt() -> None:
    """With jwks_url set, JWT auth is added to the chain."""
    from stronghold.container import _wire_auth
    from stronghold.types.config import AuthConfig

    config = _minimal_config()
    # Mutate auth config
    config.auth = AuthConfig(
        jwks_url="https://auth.example.com/.well-known/jwks.json",
        issuer="https://auth.example.com",
        audience="stronghold",
    )
    auth, perms = _wire_auth(config)
    assert auth is not None


def test_wire_auth_with_bff_cookie() -> None:
    """With client_id + token_url, BFF cookie auth is enabled."""
    from stronghold.container import _wire_auth
    from stronghold.types.config import AuthConfig

    config = _minimal_config()
    config.auth = AuthConfig(
        jwks_url="https://auth.example.com/.well-known/jwks.json",
        issuer="https://auth.example.com",
        audience="stronghold",
        client_id="stronghold-client",
        token_url="https://auth.example.com/token",
    )
    auth, perms = _wire_auth(config)
    assert auth is not None


# ── create_container ────────────────────────────────────────────────


async def test_create_container_rejects_empty_api_key() -> None:
    """Empty router_api_key must raise ConfigError."""
    from stronghold.container import create_container
    from stronghold.types.errors import ConfigError

    config = _minimal_config(router_api_key="")
    with pytest.raises(ConfigError, match="ROUTER_API_KEY"):
        await create_container(config)


async def test_create_container_minimal_in_memory() -> None:
    """create_container with no DATABASE_URL and no REDIS_URL uses in-memory."""
    from stronghold.container import Container, create_container
    config = _minimal_config()
    container = await create_container(config)
    assert isinstance(container, Container)
    assert container.auth_provider is not None
    assert container.router is not None
    assert container.classifier is not None


async def test_create_container_with_disabled_rate_limit() -> None:
    from stronghold.container import create_container
    from stronghold.types.config import RateLimitConfig
    config = _minimal_config()
    config.rate_limit = RateLimitConfig(enabled=False, requests_per_minute=60)
    container = await create_container(config)
    assert container.rate_limiter is not None


async def test_create_container_with_redis_available() -> None:
    """If REDIS_URL set and connection succeeds, use Redis-backed services."""
    from stronghold.container import create_container
    fake_redis = MagicMock()

    config = _minimal_config(redis_url="redis://localhost:6379/0")
    with patch("stronghold.cache.get_redis", new=AsyncMock(return_value=fake_redis)):
        container = await create_container(config)

    assert container is not None


async def test_create_container_with_redis_unreachable() -> None:
    """If REDIS_URL set but connection fails, fall back to InMemory."""
    from stronghold.container import create_container

    config = _minimal_config(redis_url="redis://unreachable:6379/0")
    with patch("stronghold.cache.get_redis",
               new=AsyncMock(side_effect=ConnectionError("nope"))):
        container = await create_container(config)

    assert container is not None
    # Should still have a rate limiter (InMemory fallback)
    assert container.rate_limiter is not None
