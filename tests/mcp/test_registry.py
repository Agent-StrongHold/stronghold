"""Tests for stronghold.mcp.registry — MCPRegistry.

Covers: server registration (custom + catalog), listing, filtering by org,
removal, catalog listing, status updates, image allow-list enforcement,
known-server tool attachment, and K8s-safe naming.

No mocks — uses real MCPRegistry, MCPServerSpec, MCPServer instances.
"""

from __future__ import annotations

import pytest

from stronghold.mcp.registry import KNOWN_MCP_SERVERS, MCPRegistry
from stronghold.mcp.types import (
    MCPResourceLimits,
    MCPServer,
    MCPServerSpec,
    MCPServerStatus,
    MCPSourceType,
    MCPTransport,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _allowed_spec(name: str = "test-server", **overrides: object) -> MCPServerSpec:
    """Build an MCPServerSpec with an allowed image prefix."""
    defaults: dict[str, object] = {
        "name": name,
        "image": "ghcr.io/modelcontextprotocol/server-test:latest",
    }
    defaults.update(overrides)
    return MCPServerSpec(**defaults)  # type: ignore[arg-type]


# ── Registration ─────────────────────────────────────────────────────


class TestRegister:
    def test_register_returns_server(self) -> None:
        registry = MCPRegistry()
        spec = _allowed_spec()
        server = registry.register(spec)
        assert isinstance(server, MCPServer)
        assert server.spec.name == "test-server"
        assert server.status == MCPServerStatus.PENDING

    def test_register_stores_server(self) -> None:
        registry = MCPRegistry()
        spec = _allowed_spec("my-server")
        registry.register(spec)
        assert registry.get("my-server") is not None
        assert registry.get("my-server") is not None

    def test_register_with_org_id(self) -> None:
        registry = MCPRegistry()
        spec = _allowed_spec()
        server = registry.register(spec, org_id="org-42")
        assert server.org_id == "org-42"

    def test_register_with_source_type_remote(self) -> None:
        registry = MCPRegistry()
        spec = _allowed_spec()
        server = registry.register(spec, source_type=MCPSourceType.REMOTE)
        assert server.source_type == MCPSourceType.REMOTE

    def test_register_default_source_type_is_managed(self) -> None:
        registry = MCPRegistry()
        spec = _allowed_spec()
        server = registry.register(spec)
        assert server.source_type == MCPSourceType.MANAGED

    def test_register_replaces_existing(self) -> None:
        """Re-registering the same name overwrites the previous entry."""
        registry = MCPRegistry()
        spec1 = _allowed_spec("dup", image="ghcr.io/modelcontextprotocol/server-a:1")
        spec2 = _allowed_spec("dup", image="ghcr.io/modelcontextprotocol/server-b:2")
        registry.register(spec1)
        registry.register(spec2)
        server = registry.get("dup")
        assert server is not None
        assert server.spec.image == "ghcr.io/modelcontextprotocol/server-b:2"
        assert len(registry.list_all()) == 1


# ── Image allow-list (C12) ───────────────────────────────────────────


class TestImageAllowList:
    def test_allowed_ghcr_modelcontextprotocol(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(
            name="ok",
            image="ghcr.io/modelcontextprotocol/server-github:latest",
        )
        server = registry.register(spec)
        assert server.spec.image.startswith("ghcr.io/modelcontextprotocol/")

    def test_allowed_ghcr_anthropics(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(name="ok", image="ghcr.io/anthropics/server:v1")
        server = registry.register(spec)
        assert server.spec.name == "ok"

    def test_allowed_docker_io_library(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(name="ok", image="docker.io/library/nginx:latest")
        server = registry.register(spec)
        assert server.spec.name == "ok"

    def test_allowed_mcr_microsoft(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(name="ok", image="mcr.microsoft.com/server:v1")
        server = registry.register(spec)
        assert server.spec.name == "ok"

    def test_rejected_arbitrary_image(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(name="evil", image="evil.io/malware:latest")
        with pytest.raises(ValueError, match="not from an allowed registry"):
            registry.register(spec)

    def test_rejected_dockerhub_non_library(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(name="sus", image="docker.io/randomuser/tool:v1")
        with pytest.raises(ValueError, match="not from an allowed registry"):
            registry.register(spec)

    def test_rejected_empty_image(self) -> None:
        registry = MCPRegistry()
        spec = MCPServerSpec(name="empty", image="")
        with pytest.raises(ValueError, match="not from an allowed registry"):
            registry.register(spec)


# ── Catalog registration ─────────────────────────────────────────────


class TestRegisterFromCatalog:
    def test_register_known_github(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("github")
        assert server.spec.name == "github"
        assert "github" in server.spec.image
        assert server.spec.trust_tier == "t2"
        assert len(server.tools) > 0

    def test_register_known_filesystem(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("filesystem")
        assert server.spec.name == "filesystem"
        assert len(server.tools) > 0

    def test_register_known_postgres(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("postgres")
        assert server.spec.name == "postgres"
        tool_names = [t.name for t in server.tools]
        assert "query" in tool_names

    def test_register_known_slack(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("slack")
        assert server.spec.name == "slack"
        tool_names = [t.name for t in server.tools]
        assert "send_message" in tool_names

    def test_catalog_registration_with_org(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("github", org_id="acme-corp")
        assert server.org_id == "acme-corp"

    def test_catalog_registration_with_env_overrides(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog(
            "github", env_overrides={"CUSTOM_VAR": "custom_value"}
        )
        assert server.spec.env == {"CUSTOM_VAR": "custom_value"}

    def test_catalog_unknown_name_raises(self) -> None:
        registry = MCPRegistry()
        with pytest.raises(ValueError, match="Unknown MCP server"):
            registry.register_from_catalog("nonexistent-server")

    def test_catalog_unknown_name_lists_available(self) -> None:
        registry = MCPRegistry()
        with pytest.raises(ValueError, match="github") as exc_info:
            registry.register_from_catalog("bogus")
        assert "Available:" in str(exc_info.value)

    def test_catalog_secrets_propagated(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("github")
        assert "GITHUB_PERSONAL_ACCESS_TOKEN" in server.spec.secrets


# ── Known server tool attachment ─────────────────────────────────────


class TestKnownServerToolAttachment:
    def test_known_server_gets_tools_on_register(self) -> None:
        """Registering a spec whose name matches a catalog entry gets pre-discovered tools."""
        registry = MCPRegistry()
        spec = MCPServerSpec(
            name="github",
            image="ghcr.io/modelcontextprotocol/server-github:latest",
        )
        server = registry.register(spec)
        assert len(server.tools) == len(KNOWN_MCP_SERVERS["github"]["known_tools"])

    def test_unknown_server_gets_no_tools(self) -> None:
        registry = MCPRegistry()
        spec = _allowed_spec("custom-tool")
        server = registry.register(spec)
        assert server.tools == []


# ── Listing and filtering ────────────────────────────────────────────


class TestListAll:
    def test_list_empty_registry(self) -> None:
        registry = MCPRegistry()
        assert registry.list_all() == []

    def test_list_all_returns_all(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("a"))
        registry.register(_allowed_spec("b"))
        registry.register(_allowed_spec("c"))
        assert len(registry.list_all()) == 3

    def test_list_filtered_by_org(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("a"), org_id="org-1")
        registry.register(_allowed_spec("b"), org_id="org-2")
        registry.register(_allowed_spec("c"), org_id="org-1")
        org1 = registry.list_all(org_id="org-1")
        assert len(org1) == 2
        assert all(s.org_id == "org-1" for s in org1)

    def test_list_filtered_org_includes_global(self) -> None:
        """Servers with empty org_id are visible to all orgs."""
        registry = MCPRegistry()
        registry.register(_allowed_spec("global"))  # no org_id
        registry.register(_allowed_spec("scoped"), org_id="org-x")
        visible = registry.list_all(org_id="org-x")
        names = {s.spec.name for s in visible}
        assert "global" in names
        assert "scoped" in names

    def test_list_no_filter_returns_all_orgs(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("a"), org_id="org-1")
        registry.register(_allowed_spec("b"), org_id="org-2")
        assert len(registry.list_all()) == 2


# ── Get ──────────────────────────────────────────────────────────────


class TestGet:
    def test_get_existing(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("exists"))
        assert registry.get("exists") is not None

    def test_get_nonexistent(self) -> None:
        registry = MCPRegistry()
        assert registry.get("nope") is None


# ── Remove ───────────────────────────────────────────────────────────


class TestRemove:
    def test_remove_existing(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("to-remove"))
        removed = registry.remove("to-remove")
        assert removed is not None
        assert removed.spec.name == "to-remove"
        assert registry.get("to-remove") is None

    def test_remove_nonexistent(self) -> None:
        registry = MCPRegistry()
        assert registry.remove("ghost") is None


# ── Catalog listing ──────────────────────────────────────────────────


class TestCatalog:
    def test_catalog_lists_all_known_servers(self) -> None:
        registry = MCPRegistry()
        entries = registry.catalog()
        names = {e["name"] for e in entries}
        assert names == set(KNOWN_MCP_SERVERS.keys())

    def test_catalog_shows_not_installed(self) -> None:
        registry = MCPRegistry()
        entries = registry.catalog()
        for entry in entries:
            assert entry["installed"] is False
            assert entry["status"] == "available"

    def test_catalog_shows_installed(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github")
        entries = registry.catalog()
        github_entry = next(e for e in entries if e["name"] == "github")
        assert github_entry["installed"] is True
        assert github_entry["status"] == MCPServerStatus.PENDING.value

    def test_catalog_entry_fields(self) -> None:
        registry = MCPRegistry()
        entries = registry.catalog()
        for entry in entries:
            assert "name" in entry
            assert "image" in entry
            assert "description" in entry
            assert "author" in entry
            assert "trust_tier" in entry
            assert "tool_count" in entry
            assert isinstance(entry["tool_count"], int)
            assert entry["tool_count"] > 0

    def test_catalog_tool_counts_match_known(self) -> None:
        registry = MCPRegistry()
        entries = registry.catalog()
        for entry in entries:
            name = entry["name"]
            expected = len(KNOWN_MCP_SERVERS[name].get("known_tools", []))
            assert entry["tool_count"] == expected


# ── Status updates ───────────────────────────────────────────────────


class TestUpdateStatus:
    def test_update_status_running(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("srv"))
        registry.update_status("srv", MCPServerStatus.RUNNING)
        server = registry.get("srv")
        assert server is not None
        assert server.status == MCPServerStatus.RUNNING

    def test_update_status_failed_with_error(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("srv"))
        registry.update_status("srv", MCPServerStatus.FAILED, error="CrashLoopBackOff")
        server = registry.get("srv")
        assert server is not None
        assert server.status == MCPServerStatus.FAILED
        assert server.error == "CrashLoopBackOff"

    def test_update_status_nonexistent_is_noop(self) -> None:
        """Updating status on a non-existent server does not raise."""
        registry = MCPRegistry()
        registry.update_status("ghost", MCPServerStatus.RUNNING)
        # No exception — just a no-op

    def test_status_transitions(self) -> None:
        registry = MCPRegistry()
        registry.register(_allowed_spec("lifecycle"))
        server = registry.get("lifecycle")
        assert server is not None
        assert server.status.value == "pending"

        registry.update_status("lifecycle", MCPServerStatus.DEPLOYING)
        assert server.status.value == "deploying"

        registry.update_status("lifecycle", MCPServerStatus.RUNNING)
        assert server.status.value == "running"

        registry.update_status("lifecycle", MCPServerStatus.STOPPED)
        assert server.status.value == "stopped"

        registry.update_status("lifecycle", MCPServerStatus.REMOVED)
        assert server.status.value == "removed"


# ── K8s-safe naming ──────────────────────────────────────────────────


class TestK8sNaming:
    def test_k8s_name_basic(self) -> None:
        registry = MCPRegistry()
        server = registry.register(_allowed_spec("github"))
        assert server.k8s_name == "mcp-github"

    def test_k8s_name_underscores_to_hyphens(self) -> None:
        registry = MCPRegistry()
        server = registry.register(_allowed_spec("my_custom_server"))
        assert "_" not in server.k8s_name
        assert server.k8s_name == "mcp-my-custom-server"

    def test_k8s_name_lowercase(self) -> None:
        registry = MCPRegistry()
        server = registry.register(_allowed_spec("MyServer"))
        assert server.k8s_name == server.k8s_name.lower()

    def test_k8s_name_truncated_at_63(self) -> None:
        long_name = "a" * 100
        registry = MCPRegistry()
        server = registry.register(_allowed_spec(long_name))
        assert len(server.k8s_name) <= 63


# ── MCPServer.to_dict ────────────────────────────────────────────────


class TestServerToDict:
    def test_to_dict_fields(self) -> None:
        registry = MCPRegistry()
        server = registry.register_from_catalog("github", org_id="org-99")
        d = server.to_dict()
        assert d["name"] == "github"
        assert d["source_type"] == "managed"
        assert d["status"] == "pending"
        assert d["transport"] == "sse"
        assert d["port"] == 3000
        assert d["trust_tier"] == "t2"
        assert d["org_id"] == "org-99"
        assert d["tool_count"] == len(server.tools)
        assert isinstance(d["tools"], list)
        assert len(d["tools"]) > 0
        assert "name" in d["tools"][0]
        assert "description" in d["tools"][0]

    def test_to_dict_empty_tools(self) -> None:
        registry = MCPRegistry()
        server = registry.register(_allowed_spec("custom"))
        d = server.to_dict()
        assert d["tools"] == []
        assert d["tool_count"] == 0


# ── KNOWN_MCP_SERVERS catalog integrity ──────────────────────────────


class TestKnownMCPServers:
    def test_all_known_servers_have_required_fields(self) -> None:
        for name, entry in KNOWN_MCP_SERVERS.items():
            assert "image" in entry, f"{name} missing image"
            assert "description" in entry, f"{name} missing description"
            assert "port" in entry, f"{name} missing port"
            assert "trust_tier" in entry, f"{name} missing trust_tier"
            assert "known_tools" in entry, f"{name} missing known_tools"
            assert len(entry["known_tools"]) > 0, f"{name} has no known_tools"

    def test_all_known_images_pass_allow_list(self) -> None:
        """Every image in the catalog must pass the registry allow-list."""
        registry = MCPRegistry()
        for name in KNOWN_MCP_SERVERS:
            # Should not raise
            server = registry.register_from_catalog(name)
            assert server.spec.name == name

    def test_known_server_count(self) -> None:
        """Catalog has exactly 4 known servers (github, filesystem, postgres, slack)."""
        assert len(KNOWN_MCP_SERVERS) == 4
        assert set(KNOWN_MCP_SERVERS.keys()) == {"github", "filesystem", "postgres", "slack"}


# ── MCPServerSpec defaults ───────────────────────────────────────────


class TestMCPServerSpecDefaults:
    def test_default_transport_is_sse(self) -> None:
        spec = MCPServerSpec(name="x", image="ghcr.io/modelcontextprotocol/test:v1")
        assert spec.transport == MCPTransport.SSE

    def test_default_port_is_3000(self) -> None:
        spec = MCPServerSpec(name="x", image="ghcr.io/modelcontextprotocol/test:v1")
        assert spec.port == 3000

    def test_default_trust_tier_is_t3(self) -> None:
        spec = MCPServerSpec(name="x", image="ghcr.io/modelcontextprotocol/test:v1")
        assert spec.trust_tier == "t3"

    def test_resource_limits_defaults(self) -> None:
        limits = MCPResourceLimits()
        assert limits.cpu_limit == "500m"
        assert limits.memory_limit == "256Mi"
        assert limits.cpu_request == "100m"
        assert limits.memory_request == "64Mi"
