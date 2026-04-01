"""Config-driven RBAC engine.

Provides role-based access control for agents and tools, with support for:
- Wildcard (``*``) grants for admin-like roles
- Per-role tool and agent allow-lists
- Per-role confirmation requirements for dangerous tools
- Provider-to-Stronghold role mapping (Keycloak, Entra ID, etc.)

Config format (loaded from ``config/permissions.yaml``)::

    roles:
      admin:
        tools: ["*"]
        agents: ["*"]
      engineer:
        tools: [web_search, shell, git]
        agents: [artificer, ranger]

    confirmations:
      engineer: [shell]

    role_mapping:
      keycloak:
        realm_admin: admin
        dev: engineer
"""

from __future__ import annotations

from typing import Any


class RBACEngine:
    """Evaluate role-based access from a parsed permissions config.

    Parameters
    ----------
    config:
        Dict with optional keys ``roles``, ``confirmations``, ``role_mapping``.
        See module docstring for the expected shape.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        raw_roles: dict[str, Any] = config.get("roles", {})

        # Pre-compute frozen sets for O(1) lookups.
        self._tools: dict[str, frozenset[str]] = {}
        self._agents: dict[str, frozenset[str]] = {}

        for role, perms in raw_roles.items():
            self._tools[role] = frozenset(perms.get("tools", []))
            self._agents[role] = frozenset(perms.get("agents", []))

        # Confirmation requirements: role -> frozenset of tool names.
        raw_confirmations: dict[str, list[str]] = config.get("confirmations", {})
        self._confirmations: dict[str, frozenset[str]] = {
            role: frozenset(tools) for role, tools in raw_confirmations.items()
        }

        # Provider role mapping: provider -> {provider_role -> stronghold_role}.
        self._role_mapping: dict[str, dict[str, str]] = config.get("role_mapping", {})

    # ── Access checks ───────────────────────────────────────────────

    def can_access_agent(self, role: str, agent_name: str) -> bool:
        """Return *True* if *role* is allowed to access *agent_name*."""
        allowed = self._agents.get(role)
        if allowed is None:
            return False
        return "*" in allowed or agent_name in allowed

    def can_use_tool(self, role: str, tool_name: str) -> bool:
        """Return *True* if *role* is allowed to invoke *tool_name*."""
        allowed = self._tools.get(role)
        if allowed is None:
            return False
        return "*" in allowed or tool_name in allowed

    def requires_confirmation(self, role: str, tool_name: str) -> bool:
        """Return *True* if *role* must confirm before using *tool_name*."""
        tools = self._confirmations.get(role)
        if tools is None:
            return False
        return tool_name in tools

    # ── Role mapping ────────────────────────────────────────────────

    def resolve_role(self, provider: str, provider_role: str) -> str:
        """Map an external *provider_role* to a Stronghold role.

        Returns the mapped role name, or ``""`` if no mapping exists.
        """
        provider_map = self._role_mapping.get(provider)
        if provider_map is None:
            return ""
        return provider_map.get(provider_role, "")
