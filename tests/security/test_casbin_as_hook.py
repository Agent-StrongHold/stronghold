"""Tests for CasbinToolPolicy implementing the PreToolCallHook protocol (S1.2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from stronghold.protocols.tool_hooks import (
    AllowVerdict,
    DenyVerdict,
    PreToolCallHook,
)
from stronghold.security.tool_policy import create_tool_policy
from stronghold.types.auth import AuthContext, IdentityKind


def _make_auth(user_id: str = "alice", org_id: str = "acme") -> AuthContext:
    return AuthContext(
        user_id=user_id,
        org_id=org_id,
        team_id="team-1",
        kind=IdentityKind.USER,
    )


def _policy_available() -> bool:
    return (
        Path("config/tool_policy_model.conf").exists() and Path("config/tool_policy.csv").exists()
    )


@pytest.mark.skipif(not _policy_available(), reason="Casbin policy files not available")
def test_casbin_policy_adopts_hook_protocol() -> None:
    """CasbinToolPolicy is duck-typed as a PreToolCallHook."""
    policy = create_tool_policy()
    assert isinstance(policy, PreToolCallHook)
    assert policy.name == "casbin_tool_policy"


@pytest.mark.skipif(not _policy_available(), reason="Casbin policy files not available")
async def test_casbin_allow_returns_allow_verdict() -> None:
    """When check_tool_call returns True, the hook returns AllowVerdict."""
    policy = create_tool_policy()
    # Use an identity that the default policy permits (fall back: add a policy).
    policy.add_policy("alice", "acme", "file_ops", "tool_call", "allow")
    verdict = await policy.check("file_ops", {}, _make_auth())
    assert isinstance(verdict, AllowVerdict)


@pytest.mark.skipif(not _policy_available(), reason="Casbin policy files not available")
async def test_casbin_deny_returns_deny_verdict() -> None:
    """When check_tool_call returns False, the hook returns DenyVerdict with hook_name."""
    policy = create_tool_policy()
    # Add an explicit deny for this subject/tool (overrides default * allow).
    policy.add_policy("bob", "acme", "blocked_tool", "tool_call", "deny")
    verdict = await policy.check("blocked_tool", {}, _make_auth("bob"))
    assert isinstance(verdict, DenyVerdict)
    assert verdict.hook_name == "casbin_tool_policy"
    assert "blocked_tool" in verdict.reason
