"""Tests for CasbinToolPolicy (ADR-K8S-019)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from stronghold.security.tool_policy import CasbinToolPolicy, ToolPolicyProtocol
from tests.fakes import FakeToolPolicy

MODEL_CONF = """\
[request_definition]
r = sub, org, obj, act

[policy_definition]
p = sub, org, obj, act, eft

[policy_effect]
e = some(where (p.eft == allow)) && !some(where (p.eft == deny))

[matchers]
m = (r.sub == p.sub || p.sub == "*") && (r.org == p.org || p.org == "*") && (r.obj == p.obj || p.obj == "*") && (r.act == p.act || p.act == "*")
"""

DEFAULT_POLICY = """\
p, *, *, *, tool_call, allow
p, *, *, *, task_create, allow
"""


def _make_policy(model: str = MODEL_CONF, policy: str = DEFAULT_POLICY) -> CasbinToolPolicy:
    tmp = tempfile.mkdtemp()
    model_path = Path(tmp) / "model.conf"
    policy_path = Path(tmp) / "policy.csv"
    model_path.write_text(model)
    policy_path.write_text(policy)
    return CasbinToolPolicy(str(model_path), str(policy_path))


def test_default_allows_tool_call() -> None:
    assert _make_policy().check_tool_call("alice", "acme", "web_search") is True


def test_default_allows_task_creation() -> None:
    assert _make_policy().check_task_creation("alice", "acme", "artificer") is True


def test_deny_blocks_tool_for_user() -> None:
    p = _make_policy(policy=DEFAULT_POLICY + "p, alice, *, shell, tool_call, deny\n")
    assert p.check_tool_call("alice", "acme", "shell") is False
    assert p.check_tool_call("bob", "acme", "shell") is True


def test_deny_blocks_tool_for_org() -> None:
    p = _make_policy(policy=DEFAULT_POLICY + "p, *, evil-corp, shell, tool_call, deny\n")
    assert p.check_tool_call("alice", "evil-corp", "shell") is False
    assert p.check_tool_call("alice", "acme", "shell") is True


def test_deny_blocks_task_for_user() -> None:
    p = _make_policy(policy=DEFAULT_POLICY + "p, mallory, *, forge, task_create, deny\n")
    assert p.check_task_creation("mallory", "acme", "forge") is False
    assert p.check_task_creation("alice", "acme", "forge") is True


def test_wildcard_matching() -> None:
    assert _make_policy().check_tool_call("anyone", "any-org", "any-tool") is True


def test_add_and_remove_policy() -> None:
    p = _make_policy()
    assert p.check_tool_call("alice", "acme", "danger") is True
    p.add_policy("alice", "acme", "danger", "tool_call", "deny")
    assert p.check_tool_call("alice", "acme", "danger") is False
    p.remove_policy("alice", "acme", "danger", "tool_call", "deny")
    assert p.check_tool_call("alice", "acme", "danger") is True


def test_reload_policy() -> None:
    tmp = tempfile.mkdtemp()
    mp, pp = Path(tmp) / "model.conf", Path(tmp) / "policy.csv"
    mp.write_text(MODEL_CONF)
    pp.write_text(DEFAULT_POLICY)
    p = CasbinToolPolicy(str(mp), str(pp))
    assert p.check_tool_call("alice", "acme", "shell") is True
    pp.write_text(DEFAULT_POLICY + "p, alice, *, shell, tool_call, deny\n")
    p.reload_policy()
    assert p.check_tool_call("alice", "acme", "shell") is False


def test_protocol_compliance() -> None:
    assert isinstance(_make_policy(), ToolPolicyProtocol)


def test_fake_default_allows() -> None:
    f = FakeToolPolicy()
    assert f.check_tool_call("alice", "acme", "shell") is True
    assert f.check_task_creation("alice", "acme", "forge") is True


def test_fake_deny() -> None:
    f = FakeToolPolicy()
    f.deny_tool_call("alice", "acme", "shell")
    assert f.check_tool_call("alice", "acme", "shell") is False
    assert f.check_tool_call("bob", "acme", "shell") is True
