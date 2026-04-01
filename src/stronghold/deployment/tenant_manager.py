"""Multi-tenant K8s namespace isolation manager.

Each tenant gets a dedicated K8s namespace with:
- ResourceQuota for CPU/memory limits
- NetworkPolicy for default-deny ingress isolation
- Labels for tenant/org identification

In-memory implementation for now; will be backed by persistence
once the deployment store protocol is defined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class TenantConfig:
    """Configuration for a single tenant namespace.

    Attributes:
        tenant_id: Unique tenant identifier.
        org_id: Organization this tenant belongs to.
        namespace: K8s namespace name. Auto-generated as ``stronghold-{tenant_id}``
            if not provided.
        resource_quota: CPU and memory limits for the namespace.
        created_at: Timestamp when the tenant was registered.
    """

    tenant_id: str
    org_id: str
    namespace: str = ""
    resource_quota: dict[str, str] = field(
        default_factory=lambda: {"cpu": "4", "memory": "8Gi"},
    )
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.namespace:
            self.namespace = f"stronghold-{self.tenant_id}"


class TenantManager:
    """In-memory multi-tenant namespace manager.

    Manages tenant lifecycle (create, get, list, soft-delete) and
    generates K8s manifests for namespace isolation.
    """

    def __init__(self) -> None:
        self._tenants: dict[str, TenantConfig] = {}
        self._deleted: set[str] = set()

    async def create_tenant(self, config: TenantConfig) -> TenantConfig:
        """Register a new tenant. Raises ValueError if tenant_id already exists."""
        if config.tenant_id in self._tenants:
            msg = f"Tenant '{config.tenant_id}' already exists"
            raise ValueError(msg)
        self._tenants[config.tenant_id] = config
        return config

    async def get_tenant(self, tenant_id: str) -> TenantConfig | None:
        """Return tenant config, or None if not found or deleted."""
        if tenant_id in self._deleted:
            return None
        return self._tenants.get(tenant_id)

    async def list_tenants(self) -> list[TenantConfig]:
        """Return all non-deleted tenants."""
        return [cfg for tid, cfg in self._tenants.items() if tid not in self._deleted]

    async def delete_tenant(self, tenant_id: str) -> bool:
        """Soft-delete a tenant. Returns True if found, False otherwise."""
        if tenant_id not in self._tenants or tenant_id in self._deleted:
            return False
        self._deleted.add(tenant_id)
        return True

    async def get_namespace(self, tenant_id: str) -> str:
        """Return the K8s namespace for a tenant. Raises KeyError if not found."""
        tenant = await self.get_tenant(tenant_id)
        if tenant is None:
            msg = f"Tenant '{tenant_id}' not found"
            raise KeyError(msg)
        return tenant.namespace

    def generate_namespace_manifest(self, config: TenantConfig) -> dict[str, Any]:
        """Generate K8s namespace + ResourceQuota + NetworkPolicy as a dict.

        Returns a dict with three keys:
        - ``namespace``: the Namespace resource
        - ``resource_quota``: the ResourceQuota resource
        - ``network_policy``: the default-deny NetworkPolicy
        """
        namespace = config.namespace
        labels = {
            "stronghold.io/tenant": config.tenant_id,
            "stronghold.io/org": config.org_id,
        }

        ns_manifest: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {
                "name": namespace,
                "labels": labels,
            },
        }

        rq_manifest: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {
                "name": f"{namespace}-quota",
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "hard": {
                    "requests.cpu": config.resource_quota["cpu"],
                    "requests.memory": config.resource_quota["memory"],
                },
            },
        }

        np_manifest: dict[str, Any] = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": f"{namespace}-default-deny",
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {},
                },
                "policyTypes": ["Ingress"],
                "ingress": [
                    {
                        "from": [
                            {
                                "namespaceSelector": {
                                    "matchLabels": {
                                        "stronghold.io/tenant": config.tenant_id,
                                    },
                                },
                            },
                        ],
                    },
                ],
            },
        }

        return {
            "namespace": ns_manifest,
            "resource_quota": rq_manifest,
            "network_policy": np_manifest,
        }
