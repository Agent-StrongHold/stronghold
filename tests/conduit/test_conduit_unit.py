"""Focused unit tests for Conduit helper methods (not full route_request)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_conduit(agents: dict | None = None):
    """Build a Conduit with a minimal mock container."""
    from stronghold.conduit import Conduit
    container = MagicMock()
    container.agents = agents or {}
    return Conduit(container)


# ── _fallback_agent_name ────────────────────────────────────────────


def test_fallback_returns_preferred_when_present() -> None:
    c = _make_conduit({"arbiter": MagicMock(), "ranger": MagicMock()})
    assert c._fallback_agent_name("ranger") == "ranger"


def test_fallback_returns_arbiter_when_preferred_missing() -> None:
    c = _make_conduit({"arbiter": MagicMock(), "default": MagicMock()})
    assert c._fallback_agent_name("nonexistent") == "arbiter"


def test_fallback_returns_default_when_no_arbiter() -> None:
    c = _make_conduit({"default": MagicMock(), "other": MagicMock()})
    assert c._fallback_agent_name("nonexistent") == "default"


def test_fallback_returns_first_agent_when_no_standard() -> None:
    c = _make_conduit({"zzz_weird": MagicMock(), "aaa_first": MagicMock()})
    # Dict preserves insertion order, so returns zzz_weird (first inserted)
    result = c._fallback_agent_name("nonexistent")
    assert result in ("zzz_weird", "aaa_first")


def test_fallback_raises_when_empty() -> None:
    c = _make_conduit({})
    with pytest.raises(RuntimeError, match="No agents"):
        c._fallback_agent_name()


def test_fallback_no_preference_returns_arbiter() -> None:
    c = _make_conduit({"arbiter": MagicMock(), "other": MagicMock()})
    assert c._fallback_agent_name() == "arbiter"


# ── _fallback_agent ─────────────────────────────────────────────────


def test_fallback_agent_returns_object() -> None:
    arbiter = MagicMock(name="arbiter_agent")
    c = _make_conduit({"arbiter": arbiter})
    result = c._fallback_agent("arbiter")
    assert result is arbiter


def test_fallback_agent_warns_on_arbiter_fallback(caplog) -> None:
    """If preferred=arbiter but no arbiter exists, logs warning and falls back."""
    import logging
    default = MagicMock(name="default_agent")
    c = _make_conduit({"default": default})
    with caplog.at_level(logging.WARNING):
        result = c._fallback_agent("arbiter")
    assert result is default
    assert any("Arbiter" in r.message for r in caplog.records)


def test_fallback_agent_no_warning_on_other_fallback(caplog) -> None:
    """Fallback to arbiter from preferred=other should not log the arbiter warning."""
    import logging
    arbiter = MagicMock()
    c = _make_conduit({"arbiter": arbiter})
    with caplog.at_level(logging.WARNING):
        c._fallback_agent("other")
    # No warning about arbiter missing — it was found
    assert not any("Arbiter agent missing" in r.message for r in caplog.records)


# ── route_request auth guard ────────────────────────────────────────


async def test_route_request_rejects_none_auth() -> None:
    c = _make_conduit({"arbiter": MagicMock()})
    with pytest.raises(TypeError, match="AuthContext"):
        await c.route_request(messages=[], auth=None)


async def test_route_request_rejects_wrong_type_auth() -> None:
    c = _make_conduit({"arbiter": MagicMock()})
    with pytest.raises(TypeError, match="AuthContext"):
        await c.route_request(messages=[], auth="not an auth context")


async def test_route_request_rejects_dict_auth() -> None:
    c = _make_conduit({"arbiter": MagicMock()})
    with pytest.raises(TypeError, match="AuthContext"):
        await c.route_request(messages=[], auth={"user_id": "alice"})
