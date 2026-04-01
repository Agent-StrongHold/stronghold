"""Tests for POST /v1/embeddings — OpenAI-compatible embeddings endpoint.

Uses real InMemoryEmbeddingClient (deterministic, no external calls).
Auth via StaticKeyAuthProvider. No unittest.mock.
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
from stronghold.api.routes.embeddings import router as embeddings_router
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.embeddings.client import InMemoryEmbeddingClient
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

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def embeddings_app() -> FastAPI:
    """FastAPI app with /v1/embeddings route and InMemoryEmbeddingClient."""
    app = FastAPI()
    app.include_router(embeddings_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("OK")

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
                "strengths": ["chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    warden = Warden()

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
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=warden,
            learning_store=InMemoryLearningStore(),
        )
        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    # Attach the embedding client
    container.embedding_client = InMemoryEmbeddingClient()  # type: ignore[attr-defined]
    app.state.container = container
    return app


@pytest.fixture
def no_embed_app() -> FastAPI:
    """FastAPI app without an embedding client configured."""
    app = FastAPI()
    app.include_router(embeddings_router)

    fake_llm = FakeLLMClient()
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
                "strengths": ["chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )
    prompts = InMemoryPromptManager()
    warden = Warden()

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
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=warden,
            learning_store=InMemoryLearningStore(),
        )
        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    # Do NOT set container.embedding_client — leave it absent
    app.state.container = container
    return app


# ── Auth Tests ──────────────────────────────────────────────────────


class TestEmbeddingsAuth:
    def test_no_auth_returns_401(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post("/v1/embeddings", json={"input": "hello", "model": "m"})
            assert resp.status_code == 401

    def test_wrong_key_returns_401(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": "hello", "model": "m"},
                headers={"Authorization": "Bearer wrong-key"},
            )
            assert resp.status_code == 401


# ── Validation Tests ────────────────────────────────────────────────


class TestEmbeddingsValidation:
    def test_missing_input_returns_400(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"model": "text-embedding-3-small"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400
            assert "input" in resp.json()["detail"].lower()

    def test_invalid_input_type_returns_400(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": 42, "model": "m"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400

    def test_empty_list_returns_400(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": [], "model": "m"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400


# ── Single Input ────────────────────────────────────────────────────


class TestEmbeddingsSingleInput:
    def test_string_input_returns_one_embedding(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": "hello world", "model": "text-embedding-3-small"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["object"] == "list"
            assert data["model"] == "text-embedding-3-small"
            assert len(data["data"]) == 1
            item = data["data"][0]
            assert item["object"] == "embedding"
            assert item["index"] == 0
            assert len(item["embedding"]) == 384

    def test_response_has_usage(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": "some text", "model": "m"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            usage = resp.json()["usage"]
            assert "prompt_tokens" in usage
            assert "total_tokens" in usage
            assert usage["prompt_tokens"] > 0


# ── Batch Input ─────────────────────────────────────────────────────


class TestEmbeddingsBatchInput:
    def test_list_input_returns_multiple_embeddings(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": ["alpha", "bravo", "charlie"], "model": "m"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["data"]) == 3
            indices = [d["index"] for d in data["data"]]
            assert indices == [0, 1, 2]

    def test_each_embedding_is_384_dim(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": ["one", "two"], "model": "m"},
                headers=AUTH_HEADER,
            )
            for item in resp.json()["data"]:
                assert len(item["embedding"]) == 384


# ── Determinism ─────────────────────────────────────────────────────


class TestEmbeddingsDeterminism:
    def test_same_input_same_output(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp1 = client.post(
                "/v1/embeddings",
                json={"input": "deterministic", "model": "m"},
                headers=AUTH_HEADER,
            )
            resp2 = client.post(
                "/v1/embeddings",
                json={"input": "deterministic", "model": "m"},
                headers=AUTH_HEADER,
            )
            assert resp1.json()["data"][0]["embedding"] == resp2.json()["data"][0]["embedding"]


# ── No Embedding Client Configured ──────────────────────────────────


class TestEmbeddingsNotConfigured:
    def test_returns_501_when_no_client(self, no_embed_app: FastAPI) -> None:
        with TestClient(no_embed_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": "hello", "model": "m"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 501
            assert "not configured" in resp.json()["detail"].lower()


# ── Default Model ───────────────────────────────────────────────────


class TestEmbeddingsDefaultModel:
    def test_default_model_when_omitted(self, embeddings_app: FastAPI) -> None:
        with TestClient(embeddings_app) as client:
            resp = client.post(
                "/v1/embeddings",
                json={"input": "hello"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            assert resp.json()["model"] == "text-embedding-3-small"
