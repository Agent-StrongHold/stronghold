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


def test_default_policy_allows_tool_call() -> None:
    policy = _make_policy()
    assert policy.check_tool_call("alice", "acme", "web_search") is True


def test_default_policy_allows_task_creation() -> None:
    policy = _make_policy()
    assert policy.check_task_creation("alice", "acme", "artificer") is True


def test_deny_rule_blocks_tool_for_user() -> None:
    csv = DEFAULT_POLICY + "p, alice, *, shell, tool_call, deny\n"
    policy = _make_policy(policy=csv)
    assert policy.check_tool_call("alice", "acme", "shell") is False
    assert policy.check_tool_call("bob", "acme", "shell") is True


def test_deny_rule_blocks_tool_for_org() -> None:
    csv = DEFAULT_POLICY + "p, *, evil-corp, shell, tool_call, deny\n"
    policy = _make_policy(policy=csv)
    assert policy.check_tool_call("alice", "evil-corp", "shell") is False
    assert policy.check_tool_call("alice", "acme", "shell") is True


def test_deny_rule_blocks_task_for_user() -> None:
    csv = DEFAULT_POLICY + "p, mallory, *, forge, task_create, deny\n"
    policy = _make_policy(policy=csv)
    assert policy.check_task_creation("mallory", "acme", "forge") is False
    assert policy.check_task_creation("alice", "acme", "forge") is True


def test_wildcard_matching() -> None:
    policy = _make_policy()
    assert policy.check_tool_call("anyone", "any-org", "any-tool") is True


def test_add_and_remove_policy() -> None:
    policy = _make_policy()
    assert policy.check_tool_call("alice", "acme", "danger") is True
    policy.add_policy("alice", "acme", "danger", "tool_call", "deny")
    assert policy.check_tool_call("alice", "acme", "danger") is False
    policy.remove_policy("alice", "acme", "danger", "tool_call", "deny")
    assert policy.check_tool_call("alice", "acme", "danger") is True


def test_reload_policy() -> None:
    tmp = tempfile.mkdtemp()
    model_path = Path(tmp) / "model.conf"
    policy_path = Path(tmp) / "policy.csv"
    model_path.write_text(MODEL_CONF)
    policy_path.write_text(DEFAULT_POLICY)

    policy = CasbinToolPolicy(str(model_path), str(policy_path))
    assert policy.check_tool_call("alice", "acme", "shell") is True

    # Add a deny rule to the file and reload
    policy_path.write_text(DEFAULT_POLICY + "p, alice, *, shell, tool_call, deny\n")
    policy.reload_policy()
    assert policy.check_tool_call("alice", "acme", "shell") is False


def test_protocol_compliance() -> None:
    policy = _make_policy()
    assert isinstance(policy, ToolPolicyProtocol)


def test_fake_tool_policy_default_allows() -> None:
    fake = FakeToolPolicy()
    assert fake.check_tool_call("alice", "acme", "shell") is True
    assert fake.check_task_creation("alice", "acme", "forge") is True


def test_fake_tool_policy_deny() -> None:
    fake = FakeToolPolicy()
    fake.deny_tool_call("alice", "acme", "shell")
    assert fake.check_tool_call("alice", "acme", "shell") is False
    assert fake.check_tool_call("bob", "acme", "shell") is True

    fake.deny_task_creation("mallory", "acme", "forge")
    assert fake.check_task_creation("mallory", "acme", "forge") is False
