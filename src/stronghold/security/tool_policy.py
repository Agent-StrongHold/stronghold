"""Tool Policy layer — Casbin-based access control for tool calls and tasks.

ADR-K8S-019: two policy gates evaluated at runtime:
  1. Per-tool-call: (user, org, tool, "tool_call") -> allow/deny
  2. Per-task-creation: (user, org, agent, "task_create") -> allow/deny

Policy data loaded from CSV file with runtime updates possible.
Decisions are logged for audit.

S1.2: CasbinToolPolicy also implements the PreToolCallHook protocol, so it can
be dropped into ToolDispatcher's hook chain as-is.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import casbin  # type: ignore[import-untyped]

from stronghold.protocols.tool_hooks import AllowVerdict, DenyVerdict

if TYPE_CHECKING:
    from stronghold.protocols.tool_hooks import PreToolCallVerdict
    from stronghold.types.auth import AuthContext

logger = logging.getLogger("stronghold.security.tool_policy")


@runtime_checkable
class ToolPolicyProtocol(Protocol):
    """Protocol for tool/task policy enforcement."""

    def check_tool_call(
        self,
        user_id: str,
        org_id: str,
        tool_name: str,
    ) -> bool: ...

    def check_task_creation(
        self,
        user_id: str,
        org_id: str,
        agent_name: str,
    ) -> bool: ...


class CasbinToolPolicy:
    """Casbin-backed tool policy engine.

    Uses a PERM model with request (sub, org, obj, act) and
    policy entries with explicit allow/deny effect.

    Implements the PreToolCallHook protocol (S1.2) via `check()` + `name`.
    """

    name: str = "casbin_tool_policy"

    def __init__(self, model_path: str, policy_path: str) -> None:
        self._model_path = model_path
        self._policy_path = policy_path
        self._enforcer = casbin.Enforcer(model_path, policy_path)

    async def check(
        self,
        tool_name: str,
        arguments: dict[str, Any],  # noqa: ARG002  (arguments not used by RBAC)
        auth: AuthContext,
    ) -> PreToolCallVerdict:
        """PreToolCallHook adapter — wraps check_tool_call() into a verdict."""
        allowed = self.check_tool_call(auth.user_id, auth.org_id, tool_name)
        if allowed:
            return AllowVerdict()
        return DenyVerdict(
            reason=f"RBAC denies {auth.user_id}@{auth.org_id} -> {tool_name}",
            hook_name=self.name,
        )

    def check_tool_call(
        self,
        user_id: str,
        org_id: str,
        tool_name: str,
    ) -> bool:
        result: bool = self._enforcer.enforce(user_id, org_id, tool_name, "tool_call")
        if not result:
            logger.warning(
                "Tool call DENIED: user=%s org=%s tool=%s",
                user_id,
                org_id,
                tool_name,
            )
        return result

    def check_task_creation(
        self,
        user_id: str,
        org_id: str,
        agent_name: str,
    ) -> bool:
        result: bool = self._enforcer.enforce(user_id, org_id, agent_name, "task_create")
        if not result:
            logger.warning(
                "Task creation DENIED: user=%s org=%s agent=%s",
                user_id,
                org_id,
                agent_name,
            )
        return result

    def reload_policy(self) -> None:
        self._enforcer.load_policy()
        logger.info("Tool policy reloaded from %s", self._policy_path)

    def add_policy(
        self,
        sub: str,
        org: str,
        obj: str,
        act: str,
        eft: str = "allow",
    ) -> bool:
        result: bool = self._enforcer.add_policy(sub, org, obj, act, eft)
        return result

    def remove_policy(
        self,
        sub: str,
        org: str,
        obj: str,
        act: str,
        eft: str = "allow",
    ) -> bool:
        result: bool = self._enforcer.remove_policy(sub, org, obj, act, eft)
        return result


def create_tool_policy(
    model_path: str | None = None,
    policy_path: str | None = None,
) -> CasbinToolPolicy:
    """Create a CasbinToolPolicy with default paths."""
    config_dir = Path("config")
    if model_path is None:
        model_path = str(config_dir / "tool_policy_model.conf")
    if policy_path is None:
        policy_path = str(config_dir / "tool_policy.csv")
    return CasbinToolPolicy(model_path, policy_path)
