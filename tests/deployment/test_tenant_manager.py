"""Tests for multi-tenant K8s namespace isolation.

Covers TenantConfig dataclass, TenantManager CRUD, soft-delete,
namespace generation, and K8s manifest generation (namespace +
ResourceQuota + NetworkPolicy).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from stronghold.deployment.tenant_manager import TenantConfig, TenantManager

# ── TenantConfig dataclass ──────────────────────────────────────


class TestTenantConfig:
    """TenantConfig construction and defaults."""

    def test_auto_namespace_from_tenant_id(self) -> None:
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        assert cfg.namespace == "stronghold-acme"

    def test_explicit_namespace_overrides_auto(self) -> None:
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme", namespace="custom-ns")
        assert cfg.namespace == "custom-ns"

    def test_default_resource_quota(self) -> None:
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        assert cfg.resource_quota == {"cpu": "4", "memory": "8Gi"}

    def test_custom_resource_quota(self) -> None:
        cfg = TenantConfig(
            tenant_id="acme",
            org_id="org-acme",
            resource_quota={"cpu": "16", "memory": "32Gi"},
        )
        assert cfg.resource_quota == {"cpu": "16", "memory": "32Gi"}

    def test_created_at_auto_populated(self) -> None:
        before = datetime.now(UTC)
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        after = datetime.now(UTC)
        assert before <= cfg.created_at <= after


# ── TenantManager CRUD ──────────────────────────────────────────


class TestTenantManagerCreate:
    """create_tenant registers and validates uniqueness."""

    async def test_create_tenant_returns_config(self) -> None:
        mgr = TenantManager()
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        result = await mgr.create_tenant(cfg)
        assert result.tenant_id == "acme"
        assert result.org_id == "org-acme"
        assert result.namespace == "stronghold-acme"

    async def test_create_duplicate_raises(self) -> None:
        mgr = TenantManager()
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        await mgr.create_tenant(cfg)
        with pytest.raises(ValueError, match="already exists"):
            await mgr.create_tenant(cfg)


class TestTenantManagerGet:
    """get_tenant retrieves by ID."""

    async def test_get_existing_tenant(self) -> None:
        mgr = TenantManager()
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        await mgr.create_tenant(cfg)
        result = await mgr.get_tenant("acme")
        assert result is not None
        assert result.tenant_id == "acme"

    async def test_get_missing_returns_none(self) -> None:
        mgr = TenantManager()
        result = await mgr.get_tenant("nonexistent")
        assert result is None


class TestTenantManagerList:
    """list_tenants returns all non-deleted tenants."""

    async def test_list_empty(self) -> None:
        mgr = TenantManager()
        result = await mgr.list_tenants()
        assert result == []

    async def test_list_multiple(self) -> None:
        mgr = TenantManager()
        await mgr.create_tenant(TenantConfig(tenant_id="a", org_id="org-a"))
        await mgr.create_tenant(TenantConfig(tenant_id="b", org_id="org-b"))
        result = await mgr.list_tenants()
        assert len(result) == 2
        ids = {t.tenant_id for t in result}
        assert ids == {"a", "b"}


class TestTenantManagerDelete:
    """delete_tenant performs soft delete."""

    async def test_delete_existing_returns_true(self) -> None:
        mgr = TenantManager()
        await mgr.create_tenant(TenantConfig(tenant_id="acme", org_id="org-acme"))
        result = await mgr.delete_tenant("acme")
        assert result is True

    async def test_deleted_tenant_not_in_list(self) -> None:
        mgr = TenantManager()
        await mgr.create_tenant(TenantConfig(tenant_id="acme", org_id="org-acme"))
        await mgr.delete_tenant("acme")
        result = await mgr.list_tenants()
        assert result == []

    async def test_deleted_tenant_not_gettable(self) -> None:
        mgr = TenantManager()
        await mgr.create_tenant(TenantConfig(tenant_id="acme", org_id="org-acme"))
        await mgr.delete_tenant("acme")
        result = await mgr.get_tenant("acme")
        assert result is None

    async def test_delete_missing_returns_false(self) -> None:
        mgr = TenantManager()
        result = await mgr.delete_tenant("nonexistent")
        assert result is False


# ── Namespace lookup ────────────────────────────────────────────


class TestGetNamespace:
    """get_namespace returns the namespace string for a tenant."""

    async def test_get_namespace_existing(self) -> None:
        mgr = TenantManager()
        await mgr.create_tenant(TenantConfig(tenant_id="acme", org_id="org-acme"))
        ns = await mgr.get_namespace("acme")
        assert ns == "stronghold-acme"

    async def test_get_namespace_missing_raises(self) -> None:
        mgr = TenantManager()
        with pytest.raises(KeyError, match="not found"):
            await mgr.get_namespace("nonexistent")


# ── K8s manifest generation ─────────────────────────────────────


class TestGenerateNamespaceManifest:
    """generate_namespace_manifest returns valid K8s resource dicts."""

    def test_manifest_contains_namespace(self) -> None:
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        mgr = TenantManager()
        manifest = mgr.generate_namespace_manifest(cfg)
        ns = manifest["namespace"]
        assert ns["apiVersion"] == "v1"
        assert ns["kind"] == "Namespace"
        assert ns["metadata"]["name"] == "stronghold-acme"
        labels = ns["metadata"]["labels"]
        assert labels["stronghold.io/tenant"] == "acme"
        assert labels["stronghold.io/org"] == "org-acme"

    def test_manifest_contains_resource_quota(self) -> None:
        cfg = TenantConfig(
            tenant_id="acme",
            org_id="org-acme",
            resource_quota={"cpu": "8", "memory": "16Gi"},
        )
        mgr = TenantManager()
        manifest = mgr.generate_namespace_manifest(cfg)
        rq = manifest["resource_quota"]
        assert rq["apiVersion"] == "v1"
        assert rq["kind"] == "ResourceQuota"
        assert rq["metadata"]["namespace"] == "stronghold-acme"
        hard = rq["spec"]["hard"]
        assert hard["requests.cpu"] == "8"
        assert hard["requests.memory"] == "16Gi"

    def test_manifest_contains_network_policy(self) -> None:
        cfg = TenantConfig(tenant_id="acme", org_id="org-acme")
        mgr = TenantManager()
        manifest = mgr.generate_namespace_manifest(cfg)
        np = manifest["network_policy"]
        assert np["apiVersion"] == "networking.k8s.io/v1"
        assert np["kind"] == "NetworkPolicy"
        assert np["metadata"]["namespace"] == "stronghold-acme"
        # Default-deny ingress from other namespaces
        match_labels = np["spec"]["podSelector"]["matchLabels"]
        assert match_labels == {}
        assert "Ingress" in np["spec"]["policyTypes"]
