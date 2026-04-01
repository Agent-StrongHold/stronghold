"""Tests for config-driven RBAC engine.

Covers: role resolution, tool access, agent access, wildcard support,
confirmation requirements, role mapping from external providers,
edge cases for empty/missing config.
"""

from stronghold.security.rbac import RBACEngine

# ── Config fixtures ─────────────────────────────────────────────────


def _full_config() -> dict[str, object]:
    """Full RBAC config with roles, confirmations, and role_mapping."""
    return {
        "roles": {
            "admin": {"tools": ["*"], "agents": ["*"]},
            "engineer": {
                "tools": ["web_search", "shell", "git"],
                "agents": ["artificer", "ranger"],
            },
            "operator": {
                "tools": ["ha_control", "ha_list_devices"],
                "agents": ["warden-at-arms"],
            },
            "viewer": {
                "tools": ["web_search"],
                "agents": ["ranger"],
            },
        },
        "confirmations": {
            "engineer": ["shell"],
            "operator": ["ha_control"],
        },
        "role_mapping": {
            "keycloak": {"realm_admin": "admin", "dev": "engineer"},
            "entra_id": {"Global Administrator": "admin", "Developer": "engineer"},
        },
    }


class TestCanAccessAgent:
    """Agent access checks."""

    def test_admin_wildcard_allows_any_agent(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.can_access_agent("admin", "artificer")
        assert engine.can_access_agent("admin", "some-future-agent")

    def test_engineer_allowed_agent(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.can_access_agent("engineer", "artificer")
        assert engine.can_access_agent("engineer", "ranger")

    def test_engineer_denied_agent(self) -> None:
        engine = RBACEngine(_full_config())
        assert not engine.can_access_agent("engineer", "warden-at-arms")

    def test_viewer_limited_agents(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.can_access_agent("viewer", "ranger")
        assert not engine.can_access_agent("viewer", "artificer")

    def test_unknown_role_denied(self) -> None:
        engine = RBACEngine(_full_config())
        assert not engine.can_access_agent("nonexistent", "ranger")


class TestCanUseTool:
    """Tool access checks."""

    def test_admin_wildcard_allows_any_tool(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.can_use_tool("admin", "shell")
        assert engine.can_use_tool("admin", "anything")

    def test_engineer_allowed_tool(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.can_use_tool("engineer", "web_search")
        assert engine.can_use_tool("engineer", "shell")
        assert engine.can_use_tool("engineer", "git")

    def test_engineer_denied_tool(self) -> None:
        engine = RBACEngine(_full_config())
        assert not engine.can_use_tool("engineer", "ha_control")

    def test_viewer_limited_tools(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.can_use_tool("viewer", "web_search")
        assert not engine.can_use_tool("viewer", "shell")

    def test_unknown_role_denied(self) -> None:
        engine = RBACEngine(_full_config())
        assert not engine.can_use_tool("nonexistent", "web_search")


class TestRequiresConfirmation:
    """Confirmation requirement checks."""

    def test_engineer_shell_requires_confirmation(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.requires_confirmation("engineer", "shell")

    def test_operator_ha_control_requires_confirmation(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.requires_confirmation("operator", "ha_control")

    def test_engineer_web_search_no_confirmation(self) -> None:
        engine = RBACEngine(_full_config())
        assert not engine.requires_confirmation("engineer", "web_search")

    def test_admin_never_requires_confirmation(self) -> None:
        """Admin wildcard tools should not require confirmation (not listed)."""
        engine = RBACEngine(_full_config())
        assert not engine.requires_confirmation("admin", "shell")

    def test_unknown_role_no_confirmation(self) -> None:
        engine = RBACEngine(_full_config())
        assert not engine.requires_confirmation("nonexistent", "shell")


class TestResolveRole:
    """Provider role mapping resolution."""

    def test_keycloak_admin_mapping(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.resolve_role("keycloak", "realm_admin") == "admin"

    def test_keycloak_dev_mapping(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.resolve_role("keycloak", "dev") == "engineer"

    def test_entra_id_mapping(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.resolve_role("entra_id", "Global Administrator") == "admin"
        assert engine.resolve_role("entra_id", "Developer") == "engineer"

    def test_unknown_provider_returns_empty(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.resolve_role("unknown_provider", "admin") == ""

    def test_unknown_provider_role_returns_empty(self) -> None:
        engine = RBACEngine(_full_config())
        assert engine.resolve_role("keycloak", "nonexistent_role") == ""


class TestEdgeCases:
    """Edge cases and empty config."""

    def test_empty_config(self) -> None:
        engine = RBACEngine({})
        assert not engine.can_use_tool("admin", "shell")
        assert not engine.can_access_agent("admin", "ranger")
        assert not engine.requires_confirmation("admin", "shell")
        assert engine.resolve_role("keycloak", "admin") == ""

    def test_roles_only_no_mapping(self) -> None:
        config: dict[str, object] = {
            "roles": {
                "admin": {"tools": ["*"], "agents": ["*"]},
            },
        }
        engine = RBACEngine(config)
        assert engine.can_use_tool("admin", "anything")
        assert engine.can_access_agent("admin", "anything")
        assert engine.resolve_role("keycloak", "admin") == ""

    def test_role_with_empty_tools_list(self) -> None:
        config: dict[str, object] = {
            "roles": {
                "restricted": {"tools": [], "agents": ["ranger"]},
            },
        }
        engine = RBACEngine(config)
        assert not engine.can_use_tool("restricted", "web_search")
        assert engine.can_access_agent("restricted", "ranger")

    def test_role_with_empty_agents_list(self) -> None:
        config: dict[str, object] = {
            "roles": {
                "toolonly": {"tools": ["web_search"], "agents": []},
            },
        }
        engine = RBACEngine(config)
        assert engine.can_use_tool("toolonly", "web_search")
        assert not engine.can_access_agent("toolonly", "ranger")

    def test_confirmations_without_roles_key(self) -> None:
        config: dict[str, object] = {
            "confirmations": {"engineer": ["shell"]},
        }
        engine = RBACEngine(config)
        # No roles defined, so tool access denied, but confirmation still tracked
        assert not engine.can_use_tool("engineer", "shell")
        assert engine.requires_confirmation("engineer", "shell")

    def test_multiple_providers_in_role_mapping(self) -> None:
        engine = RBACEngine(_full_config())
        # Both providers should work independently
        assert engine.resolve_role("keycloak", "realm_admin") == "admin"
        assert engine.resolve_role("entra_id", "Global Administrator") == "admin"
        # Cross-provider roles should not leak
        assert engine.resolve_role("keycloak", "Global Administrator") == ""
        assert engine.resolve_role("entra_id", "realm_admin") == ""
