"""Tests for A2A peer endpoint (ADR-K8S-028)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.a2a import _tasks, router as a2a_router
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.fakes import FakeLLMClient, make_test_container

AUTH = {"Authorization": "Bearer sk-test"}


@pytest.fixture(autouse=True)
def _clear_tasks() -> None:
    _tasks.clear()


@pytest.fixture
def a2a_app() -> FastAPI:
    app = FastAPI()
    app.include_router(a2a_router)
    llm = FakeLLMClient()
    llm.set_simple_response("ok")
    container = make_test_container(fake_llm=llm)

    # Register a test agent
    test_agent = Agent(
        identity=AgentIdentity(
            name="test-agent",
            description="A test agent for A2A",
            tools=("web_search",),
            reasoning_strategy="direct",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=ContextBuilder(),
        prompt_manager=InMemoryPromptManager(),
        warden=Warden(),
    )
    container.agents["test-agent"] = test_agent

    app.state.container = container
    return app


@pytest.fixture
def client(a2a_app: FastAPI) -> TestClient:
    return TestClient(a2a_app)


# ── Agent Cards ──────────────────────────────────────────────────────


def test_agent_cards_list(client: TestClient) -> None:
    resp = client.get("/a2a/agent_cards/list", headers=AUTH)
    assert resp.status_code == 200
    cards = resp.json()["agent_cards"]
    assert len(cards) > 0
    # All cards have required fields
    for card in cards:
        assert "id" in card
        assert "name" in card
        assert "capabilities" in card


def test_agent_cards_list_requires_auth(client: TestClient) -> None:
    resp = client.get("/a2a/agent_cards/list")
    assert resp.status_code == 401


def test_agent_cards_get(client: TestClient) -> None:
    # Get the first agent name from list
    cards = client.get("/a2a/agent_cards/list", headers=AUTH).json()["agent_cards"]
    agent_id = cards[0]["id"]

    resp = client.get(f"/a2a/agent_cards/get/{agent_id}", headers=AUTH)
    assert resp.status_code == 200
    card = resp.json()
    assert card["id"] == agent_id
    assert "capabilities" in card
    assert "tools" in card["capabilities"]


def test_agent_cards_get_not_found(client: TestClient) -> None:
    resp = client.get("/a2a/agent_cards/get/nonexistent", headers=AUTH)
    assert resp.status_code == 404


# ── Task Lifecycle ───────────────────────────────────────────────────


def test_task_create(client: TestClient) -> None:
    cards = client.get("/a2a/agent_cards/list", headers=AUTH).json()["agent_cards"]
    agent_id = cards[0]["id"]

    resp = client.post("/a2a/tasks/create", json={
        "agent_id": agent_id,
        "messages": [{"role": "user", "content": "Hello"}],
    }, headers=AUTH)
    assert resp.status_code == 201
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "submitted"


def test_task_create_missing_agent(client: TestClient) -> None:
    resp = client.post("/a2a/tasks/create", json={
        "agent_id": "nonexistent",
        "messages": [{"role": "user", "content": "Hello"}],
    }, headers=AUTH)
    assert resp.status_code == 404


def test_task_create_missing_messages(client: TestClient) -> None:
    cards = client.get("/a2a/agent_cards/list", headers=AUTH).json()["agent_cards"]
    resp = client.post("/a2a/tasks/create", json={
        "agent_id": cards[0]["id"],
    }, headers=AUTH)
    assert resp.status_code == 400


def test_task_get(client: TestClient) -> None:
    cards = client.get("/a2a/agent_cards/list", headers=AUTH).json()["agent_cards"]
    create_resp = client.post("/a2a/tasks/create", json={
        "agent_id": cards[0]["id"],
        "messages": [{"role": "user", "content": "Hello"}],
    }, headers=AUTH)
    task_id = create_resp.json()["task_id"]

    resp = client.get(f"/a2a/tasks/get/{task_id}", headers=AUTH)
    assert resp.status_code == 200
    task = resp.json()
    assert task["id"] == task_id
    assert task["status"] == "submitted"


def test_task_get_not_found(client: TestClient) -> None:
    resp = client.get("/a2a/tasks/get/nonexistent", headers=AUTH)
    assert resp.status_code == 404


def test_task_cancel(client: TestClient) -> None:
    cards = client.get("/a2a/agent_cards/list", headers=AUTH).json()["agent_cards"]
    create_resp = client.post("/a2a/tasks/create", json={
        "agent_id": cards[0]["id"],
        "messages": [{"role": "user", "content": "Hello"}],
    }, headers=AUTH)
    task_id = create_resp.json()["task_id"]

    resp = client.post(f"/a2a/tasks/cancel/{task_id}", headers=AUTH)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Verify state persisted
    get_resp = client.get(f"/a2a/tasks/get/{task_id}", headers=AUTH)
    assert get_resp.json()["status"] == "cancelled"


def test_task_cancel_not_found(client: TestClient) -> None:
    resp = client.post("/a2a/tasks/cancel/nonexistent", headers=AUTH)
    assert resp.status_code == 404


def test_task_cancel_already_cancelled(client: TestClient) -> None:
    cards = client.get("/a2a/agent_cards/list", headers=AUTH).json()["agent_cards"]
    create_resp = client.post("/a2a/tasks/create", json={
        "agent_id": cards[0]["id"],
        "messages": [{"role": "user", "content": "Hello"}],
    }, headers=AUTH)
    task_id = create_resp.json()["task_id"]

    client.post(f"/a2a/tasks/cancel/{task_id}", headers=AUTH)
    resp = client.post(f"/a2a/tasks/cancel/{task_id}", headers=AUTH)
    assert resp.status_code == 409


def test_task_create_requires_auth(client: TestClient) -> None:
    resp = client.post("/a2a/tasks/create", json={
        "agent_id": "test",
        "messages": [{"role": "user", "content": "Hello"}],
    })
    assert resp.status_code == 401
