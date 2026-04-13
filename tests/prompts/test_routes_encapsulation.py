"""Tests for H21: prompts/routes.py must not access pm._versions/_labels.

The old code accessed private attributes (``pm._versions``, ``pm._labels``,
``pm._scoped_name``) directly from route handlers. This breaks with
PgPromptManager (which has no such attrs) and violates encapsulation.

After the fix, routes use public accessor methods on the PromptManager protocol.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.routes import _approvals
from stronghold.prompts.routes import router as prompts_router
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeLLMClient

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture(autouse=True)
def _clear_approvals() -> None:
    _approvals.clear()


class MinimalPromptManager:
    """Prompt manager that exposes ONLY the public protocol methods.

    Has NO _versions, _labels, or _scoped_name attributes.
    If routes.py accesses private attrs, tests using this will crash with
    AttributeError -- proving the encapsulation violation.
    """

    def __init__(self) -> None:
        # Internal storage -- NOT exposed as _versions/_labels
        self._store: dict[str, dict[int, tuple[str, dict[str, Any]]]] = {}
        self._label_map: dict[str, dict[str, int]] = {}
        self._next_ver: dict[str, int] = {}

    async def get(self, name: str, *, label: str = "production", org_id: str = "") -> str:
        content, _ = await self.get_with_config(name, label=label, org_id=org_id)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
        org_id: str = "",
    ) -> tuple[str, dict[str, Any]]:
        labels = self._label_map.get(name, {})
        version = labels.get(label)
        if version is None:
            versions = self._store.get(name, {})
            if not versions:
                return ("", {})
            version = max(versions)
        versions = self._store.get(name, {})
        entry = versions.get(version)
        if entry is None:
            return ("", {})
        return entry

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
        org_id: str = "",
    ) -> None:
        if name not in self._store:
            self._store[name] = {}
            self._label_map[name] = {}
            self._next_ver[name] = 1
        version = self._next_ver[name]
        self._next_ver[name] = version + 1
        self._store[name][version] = (content, config or {})
        if label:
            self._label_map[name][label] = version
        self._label_map[name]["latest"] = version
        if version == 1 and "production" not in self._label_map[name]:
            self._label_map[name]["production"] = version

    async def list_prompts(self) -> list[dict[str, Any]]:
        """Public API: list all prompts with metadata."""
        result = []
        for name in sorted(self._store.keys()):
            labels = self._label_map.get(name, {})
            versions = self._store.get(name, {})
            latest_version = max(versions.keys()) if versions else 0
            content, config = versions.get(latest_version, ("", {}))
            result.append(
                {
                    "name": name,
                    "versions": len(versions),
                    "labels": labels,
                    "latest_version": latest_version,
                    "content_preview": content[:100] + "..." if len(content) > 100 else content,
                }
            )
        return result

    async def get_version_history(self, name: str) -> dict[str, Any] | None:
        """Public API: get full version history for a prompt."""
        versions = self._store.get(name)
        if not versions:
            return None
        labels = self._label_map.get(name, {})
        version_labels: dict[int, list[str]] = {}
        for lbl, ver in labels.items():
            version_labels.setdefault(ver, []).append(lbl)
        version_list = []
        for ver in sorted(versions.keys()):
            content, config = versions[ver]
            version_list.append(
                {
                    "version": ver,
                    "labels": version_labels.get(ver, []),
                    "content_preview": content[:100] + "..." if len(content) > 100 else content,
                    "config": config,
                }
            )
        return {"name": name, "versions": version_list, "labels": labels}

    async def get_label_version(self, name: str, label: str) -> int | None:
        """Public API: get the version number for a given label."""
        labels = self._label_map.get(name, {})
        return labels.get(label)

    async def set_label(self, name: str, label: str, version: int) -> None:
        """Public API: set a label to point at a specific version."""
        if name not in self._label_map:
            self._label_map[name] = {}
        self._label_map[name][label] = version

    async def get_latest_version(self, name: str) -> int:
        """Public API: get the latest version number for a prompt."""
        versions = self._store.get(name, {})
        return max(versions.keys()) if versions else 0

    async def get_version_content(
        self,
        name: str,
        version: int,
    ) -> tuple[str, dict[str, Any]] | None:
        """Public API: get content and config for a specific version."""
        versions = self._store.get(name, {})
        entry = versions.get(version)
        if entry is None:
            return None
        return entry

    async def has_version(self, name: str, version: int) -> bool:
        """Public API: check whether a specific version exists."""
        versions = self._store.get(name, {})
        return version in versions

    def scoped_name(self, name: str, org_id: str = "") -> str:
        """Public API: build org-scoped prompt key."""
        is_shared = name.startswith("agent.") or name.startswith("system.")
        if not org_id or org_id == "__system__" or is_shared:
            return name
        return f"{org_id}:{name}"


def _make_app(pm: Any = None) -> FastAPI:
    """Build a FastAPI app with prompt routes, optionally with a custom prompt manager."""
    app = FastAPI()
    app.include_router(prompts_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")

    config = StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    prompts = pm or InMemoryPromptManager()
    warden = Warden()
    audit_log = InMemoryAuditLog()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()

    async def setup() -> Container:
        await prompts.upsert("test.soul", "You are version 1.", label="production")
        await prompts.upsert("test.soul", "You are version 2.", label="staging")
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        default_agent = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
        )

        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=learning_store,
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            audit_log=audit_log,
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=audit_log,
            ),
            tracer=NoopTracingBackend(),
            context_builder=context_builder,
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestRoutesWithMinimalPromptManager:
    """Routes must work with a PromptManager that has no private attrs.

    This proves the routes use public API only, not _versions/_labels.
    """

    def test_list_prompts_uses_public_api(self) -> None:
        """GET /v1/stronghold/prompts should work without _versions/_labels."""
        app = _make_app(pm=MinimalPromptManager())
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/prompts", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()
            names = [p["name"] for p in data["prompts"]]
            assert "test.soul" in names

    def test_get_versions_uses_public_api(self) -> None:
        """GET /v1/stronghold/prompts/{name}/versions should work without _versions."""
        from stronghold.prompts.routes import get_versions

        app = FastAPI()
        app.add_api_route(
            "/v1/stronghold/prompts/{name:path}/versions",
            get_versions,
            methods=["GET"],
        )
        pm = MinimalPromptManager()

        async def seed() -> None:
            await pm.upsert("test.soul", "Version 1", label="production")
            await pm.upsert("test.soul", "Version 2", label="staging")

        asyncio.get_event_loop().run_until_complete(seed())

        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("ok")
        config = StrongholdConfig(
            providers={
                "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000}
            },
            models={
                "m": {
                    "provider": "test",
                    "litellm_id": "t/m",
                    "tier": "medium",
                    "quality": 0.7,
                    "speed": 500,
                    "strengths": ["code"],
                }
            },
            task_types={"chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"])},
            permissions={"admin": ["*"]},
            router_api_key="sk-test",
        )
        warden = Warden()
        audit_log = InMemoryAuditLog()
        container = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=pm,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            audit_log=audit_log,
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=audit_log,
            ),
            tracer=NoopTracingBackend(),
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={},
        )
        app.state.container = container

        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/prompts/test.soul/versions", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["versions"]) == 2

    def test_get_prompt_uses_public_api(self) -> None:
        """GET /v1/stronghold/prompts/{name} should not access _labels directly."""
        app = _make_app(pm=MinimalPromptManager())
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/prompts/test.soul", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "test.soul"
            assert data["content"] == "You are version 1."
            # The version field should be populated via public API
            assert data["version"] is not None

    def test_upsert_uses_public_api(self) -> None:
        """PUT /v1/stronghold/prompts/{name} should not access _versions/_scoped_name."""
        app = _make_app(pm=MinimalPromptManager())
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/prompts/test.soul",
                json={"content": "Version 3.", "label": "staging"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["version"] == 3

    def test_promote_label_uses_public_api(self) -> None:
        """POST /v1/stronghold/prompts/{name}/promote should not access _labels."""
        app = _make_app(pm=MinimalPromptManager())
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/prompts/test.soul/promote",
                json={"from_label": "staging", "to_label": "production"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["version"] == 2

    def test_diff_uses_public_api(self) -> None:
        """GET /v1/stronghold/prompts/{name}/diff should not access _versions."""
        from stronghold.prompts.routes import get_diff

        app = FastAPI()
        app.add_api_route(
            "/v1/stronghold/prompts/{name:path}/diff",
            get_diff,
            methods=["GET"],
        )
        pm = MinimalPromptManager()

        async def seed() -> None:
            await pm.upsert("test.soul", "Version 1", label="production")
            await pm.upsert("test.soul", "Version 2", label="staging")

        asyncio.get_event_loop().run_until_complete(seed())

        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("ok")
        config = StrongholdConfig(
            providers={
                "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000}
            },
            models={
                "m": {
                    "provider": "test",
                    "litellm_id": "t/m",
                    "tier": "medium",
                    "quality": 0.7,
                    "speed": 500,
                    "strengths": ["code"],
                }
            },
            task_types={"chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"])},
            permissions={"admin": ["*"]},
            router_api_key="sk-test",
        )
        warden = Warden()
        audit_log = InMemoryAuditLog()
        container = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=pm,
            learning_store=InMemoryLearningStore(),
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            audit_log=audit_log,
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=audit_log,
            ),
            tracer=NoopTracingBackend(),
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={},
        )
        app.state.container = container

        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/prompts/test.soul/diff?from_version=1&to_version=2",
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200

    def test_request_approval_uses_public_api(self) -> None:
        """POST /v1/stronghold/prompts/{name}/request-approval should not access _versions."""
        app = _make_app(pm=MinimalPromptManager())
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/prompts/test.soul/request-approval",
                json={"version": 2, "notes": "Ready"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200

    def test_approve_prompt_uses_public_api(self) -> None:
        """POST /v1/stronghold/prompts/{name}/approve should not access _labels."""
        app = _make_app(pm=MinimalPromptManager())
        with TestClient(app) as client:
            # Submit approval request first
            client.post(
                "/v1/stronghold/prompts/test.soul/request-approval",
                json={"version": 2, "notes": "Ready"},
                headers=AUTH_HEADER,
            )
            resp = client.post(
                "/v1/stronghold/prompts/test.soul/approve",
                json={"version": 2},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["promoted_to"] == "production"


class TestNoPrivateAttrAccess:
    """Verify routes.py source code does not reference pm._versions or pm._labels."""

    def test_routes_source_has_no_private_attr_access(self) -> None:
        """Grep the routes source for private attribute access patterns."""
        import inspect

        from stronghold.prompts import routes

        source = inspect.getsource(routes)
        # After the fix, these patterns must not appear in the source
        assert "pm._versions" not in source, (
            "routes.py must not access pm._versions -- use public accessor methods"
        )
        assert "pm._labels" not in source, (
            "routes.py must not access pm._labels -- use public accessor methods"
        )
        assert "pm._scoped_name" not in source, (
            "routes.py must not access pm._scoped_name -- use public accessor methods"
        )
