"""Tool Policy layer — Casbin-based access control for tool calls and tasks.

ADR-K8S-019: two policy gates evaluated at runtime:
  1. Per-tool-call: (user, org, tool, "tool_call") -> allow/deny
  2. Per-task-creation: (user, org, agent, "task_create") -> allow/deny
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

import casbin

logger = logging.getLogger("stronghold.security.tool_policy")


@runtime_checkable
class ToolPolicyProtocol(Protocol):
    def check_tool_call(self, user_id: str, org_id: str, tool_name: str) -> bool: ...
    def check_task_creation(self, user_id: str, org_id: str, agent_name: str) -> bool: ...


class CasbinToolPolicy:
    def __init__(self, model_path: str, policy_path: str) -> None:
        self._model_path = model_path
        self._policy_path = policy_path
        self._enforcer = casbin.Enforcer(model_path, policy_path)

    def check_tool_call(self, user_id: str, org_id: str, tool_name: str) -> bool:
        result: bool = self._enforcer.enforce(user_id, org_id, tool_name, "tool_call")
        if not result:
            logger.warning("Tool call DENIED: user=%s org=%s tool=%s", user_id, org_id, tool_name)
        return result

    def check_task_creation(self, user_id: str, org_id: str, agent_name: str) -> bool:
        result: bool = self._enforcer.enforce(user_id, org_id, agent_name, "task_create")
        if not result:
            logger.warning("Task creation DENIED: user=%s org=%s agent=%s", user_id, org_id, agent_name)
        return result

    def reload_policy(self) -> None:
        self._enforcer.load_policy()

    def add_policy(self, sub: str, org: str, obj: str, act: str, eft: str = "allow") -> bool:
        return bool(self._enforcer.add_policy(sub, org, obj, act, eft))

    def remove_policy(self, sub: str, org: str, obj: str, act: str, eft: str = "allow") -> bool:
        return bool(self._enforcer.remove_policy(sub, org, obj, act, eft))


def create_tool_policy(model_path: str | None = None, policy_path: str | None = None) -> CasbinToolPolicy:
    config_dir = Path("config")
    return CasbinToolPolicy(
        model_path or str(config_dir / "tool_policy_model.conf"),
        policy_path or str(config_dir / "tool_policy.csv"),
    )
