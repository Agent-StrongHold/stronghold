"""Tests for api/app.py — the FastAPI app factory and dashboard routes."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def test_create_app_under_pytest() -> None:
    """create_app detects pytest env and uses test middleware, not lifespan."""
    from stronghold.api.app import create_app
    os.environ["PYTEST_CURRENT_TEST"] = "test"
    try:
        app = create_app()
        assert app.title == "Stronghold"
        assert app.version == "0.1.0"
    finally:
        # Leave the env alone — pytest sets this
        pass


def test_dashboard_root_login_page() -> None:
    """GET / returns the login HTML page."""
    from stronghold.api.app import create_app
    app = create_app()
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_dashboard_greathall() -> None:
    from stronghold.api.app import create_app
    app = create_app()
    client = TestClient(app)
    resp = client.get("/greathall")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_dashboard_prompts() -> None:
    from stronghold.api.app import create_app
    app = create_app()
    client = TestClient(app)
    resp = client.get("/prompts")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_dashboard_fallback_when_file_missing() -> None:
    """If all candidate paths are missing, returns fallback message."""
    from stronghold.api import app as app_module

    # Hit the inner helper directly with a bogus filename
    app = app_module.create_app()
    client = TestClient(app)
    # A route that would call _find_dashboard_file with a missing file —
    # we can't directly; all routes request real files. Instead, verify
    # the fallback text is reachable by mocking Path.exists to False
    with patch("pathlib.Path.exists", return_value=False):
        resp = client.get("/")
    assert resp.status_code == 200
    # Should contain the fallback HTML
    assert "Stronghold" in resp.text


async def test_lifespan_without_pytest_env(monkeypatch) -> None:
    """Lifespan context manager runs startup + shutdown."""
    from stronghold.api.app import lifespan
    from fastapi import FastAPI

    # Clear pytest env var for this test
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("STRONGHOLD_DISABLE_REACTOR_AUTOSTART", "1")

    fake_container = MagicMock()
    fake_container.reactor = MagicMock()
    fake_container.reactor.stop = MagicMock()
    fake_container.db_pool = None
    fake_container.sa_engine = None
    fake_container.redis_client = None

    with patch("stronghold.api.app.load_config", return_value=MagicMock()), \
         patch("stronghold.api.app.create_container",
               new=AsyncMock(return_value=fake_container)):
        app = FastAPI()
        async with lifespan(app):
            assert hasattr(app.state, "container")

    fake_container.reactor.stop.assert_called_once()


async def test_lifespan_closes_db_pool() -> None:
    """Lifespan shuts down db_pool if present."""
    from stronghold.api.app import lifespan
    from fastapi import FastAPI

    fake_container = MagicMock()
    fake_container.reactor = MagicMock()
    fake_container.db_pool = MagicMock()  # truthy
    fake_container.sa_engine = None
    fake_container.redis_client = None

    with patch("stronghold.api.app.load_config", return_value=MagicMock()), \
         patch("stronghold.api.app.create_container",
               new=AsyncMock(return_value=fake_container)), \
         patch("stronghold.persistence.close_pool", new=AsyncMock()) as close_pool:
        app = FastAPI()
        async with lifespan(app):
            pass
        close_pool.assert_awaited_once()


async def test_lifespan_closes_sa_engine() -> None:
    from stronghold.api.app import lifespan
    from fastapi import FastAPI

    fake_container = MagicMock()
    fake_container.reactor = MagicMock()
    fake_container.db_pool = None
    fake_container.sa_engine = MagicMock()  # truthy
    fake_container.redis_client = None

    with patch("stronghold.api.app.load_config", return_value=MagicMock()), \
         patch("stronghold.api.app.create_container",
               new=AsyncMock(return_value=fake_container)), \
         patch("stronghold.models.engine.close_engine", new=AsyncMock()) as close_engine:
        app = FastAPI()
        async with lifespan(app):
            pass
        close_engine.assert_awaited_once()


async def test_lifespan_closes_redis() -> None:
    from stronghold.api.app import lifespan
    from fastapi import FastAPI

    fake_container = MagicMock()
    fake_container.reactor = MagicMock()
    fake_container.db_pool = None
    fake_container.sa_engine = None
    fake_container.redis_client = MagicMock()

    with patch("stronghold.api.app.load_config", return_value=MagicMock()), \
         patch("stronghold.api.app.create_container",
               new=AsyncMock(return_value=fake_container)), \
         patch("stronghold.cache.close_redis", new=AsyncMock()) as close_redis:
        app = FastAPI()
        async with lifespan(app):
            pass
        close_redis.assert_awaited_once()
