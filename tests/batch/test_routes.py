"""Tests for batch API routes: submit, poll, list, cancel."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.api.routes.batch import router as batch_router
from stronghold.batch.manager import InMemoryBatchManager
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
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


@pytest.fixture
def batch_app() -> FastAPI:
    """Create a FastAPI app with batch routes and real components."""
    app = FastAPI()
    app.include_router(batch_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")

    config = StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000},
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

    prompts = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    warden = Warden()
    context_builder = ContextBuilder()
    batch_manager = InMemoryBatchManager()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        default_agent = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
                memory_config={"learnings": True},
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
            learning_store=learning_store,
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
            audit_log=InMemoryAuditLog(),
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=InMemoryAuditLog(),
            ),
            tracer=NoopTracingBackend(),
            context_builder=context_builder,
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            task_queue=InMemoryTaskQueue(),
            batch_manager=batch_manager,
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestSubmitBatchTask:
    def test_submit_returns_200_with_task_id(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "task_id" in data
            assert data["status"] == "submitted"

    def test_submit_empty_messages_returns_400(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": []},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 400

    def test_submit_requires_auth(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": [{"role": "user", "content": "hello"}]},
            )
            assert resp.status_code == 401

    def test_submit_with_callback_url(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.post(
                "/v1/stronghold/batch/tasks",
                json={
                    "messages": [{"role": "user", "content": "hello"}],
                    "callback_url": "https://example.com/webhook",
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            assert "task_id" in resp.json()


class TestPollBatchTask:
    def test_poll_returns_task_status(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            # Submit first
            submit_resp = client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"Authorization": "Bearer sk-test"},
            )
            task_id = submit_resp.json()["task_id"]

            # Poll
            resp = client.get(
                f"/v1/stronghold/batch/tasks/{task_id}",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["task_id"] == task_id
            assert data["status"] == "submitted"
            assert "created_at" in data

    def test_poll_nonexistent_returns_404(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.get(
                "/v1/stronghold/batch/tasks/nonexistent",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 404

    def test_poll_requires_auth(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.get("/v1/stronghold/batch/tasks/some-id")
            assert resp.status_code == 401


class TestListBatchTasks:
    def test_list_returns_user_tasks(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            # Submit two tasks
            client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": [{"role": "user", "content": "task 1"}]},
                headers={"Authorization": "Bearer sk-test"},
            )
            client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": [{"role": "user", "content": "task 2"}]},
                headers={"Authorization": "Bearer sk-test"},
            )

            resp = client.get(
                "/v1/stronghold/batch/tasks",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "tasks" in data
            assert len(data["tasks"]) >= 2

    def test_list_requires_auth(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.get("/v1/stronghold/batch/tasks")
            assert resp.status_code == 401


class TestCancelBatchTask:
    def test_cancel_returns_200(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            # Submit
            submit_resp = client.post(
                "/v1/stronghold/batch/tasks",
                json={"messages": [{"role": "user", "content": "hello"}]},
                headers={"Authorization": "Bearer sk-test"},
            )
            task_id = submit_resp.json()["task_id"]

            # Cancel
            resp = client.delete(
                f"/v1/stronghold/batch/tasks/{task_id}",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "cancelled"

    def test_cancel_nonexistent_returns_404(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.delete(
                "/v1/stronghold/batch/tasks/nonexistent",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 404

    def test_cancel_requires_auth(self, batch_app: FastAPI) -> None:
        with TestClient(batch_app) as client:
            resp = client.delete("/v1/stronghold/batch/tasks/some-id")
            assert resp.status_code == 401
