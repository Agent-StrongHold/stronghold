"""Tests for the prompt playground runner and API routes.

Uses real PlaygroundRunner with FakeLLMClient — no mocks.
API route tests build a real Container with StaticKeyAuthProvider.
"""

from __future__ import annotations

import asyncio

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
from stronghold.playground.runner import (
    ComparisonRun,
    PlaygroundResult,
    PlaygroundRunner,
    CaseResult,
)
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


# ── Unit tests: PlaygroundRunner ──────────────────────────────────────


class TestPlaygroundRunReturnsContent:
    """run() returns content from FakeLLMClient."""

    async def test_run_returns_content(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Hello, world!")
        runner = PlaygroundRunner(llm=llm)

        result = await runner.run(
            system_prompt="You are helpful.",
            test_messages=[{"role": "user", "content": "Hi"}],
        )

        assert isinstance(result, PlaygroundResult)
        assert result.content == "Hello, world!"

    async def test_run_returns_model(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        runner = PlaygroundRunner(llm=llm)

        result = await runner.run(
            system_prompt="sys",
            test_messages=[{"role": "user", "content": "test"}],
            model="gpt-4",
        )

        assert result.model == "gpt-4"

    async def test_run_returns_token_usage(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        runner = PlaygroundRunner(llm=llm)

        result = await runner.run(
            system_prompt="sys",
            test_messages=[{"role": "user", "content": "test"}],
        )

        assert result.input_tokens == 10
        assert result.output_tokens == 20


class TestPlaygroundRunTracksLatency:
    """run() tracks latency in milliseconds."""

    async def test_latency_is_non_negative(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("fast")
        runner = PlaygroundRunner(llm=llm)

        result = await runner.run(
            system_prompt="sys",
            test_messages=[{"role": "user", "content": "test"}],
        )

        assert result.latency_ms >= 0


class TestPlaygroundRunHandlesError:
    """run() handles LLM errors gracefully."""

    async def test_error_returns_error_field(self) -> None:
        llm = FakeLLMClient()
        # Don't set any responses — empty list will cause no responses
        # Instead, set responses to something that triggers an error
        llm.responses = []  # Force the default response path

        # Create a broken LLM that raises
        class BrokenLLM:
            async def complete(
                self, messages: list[object], model: str, **kw: object
            ) -> dict[str, object]:
                msg = "LLM is down"
                raise RuntimeError(msg)

            async def stream(self, messages: list[object], model: str, **kw: object) -> None:
                yield ""  # type: ignore[misc]

        runner = PlaygroundRunner(llm=BrokenLLM())  # type: ignore[arg-type]

        result = await runner.run(
            system_prompt="sys",
            test_messages=[{"role": "user", "content": "test"}],
        )

        assert result.error == "LLM is down"
        assert result.content == ""
        assert result.latency_ms >= 0


class TestPlaygroundCompare:
    """compare() runs both test and production prompts."""

    async def test_compare_returns_both_results(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            {
                "id": "r1",
                "object": "chat.completion",
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "test output"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            },
            {
                "id": "r2",
                "object": "chat.completion",
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "prod output"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            },
        )
        runner = PlaygroundRunner(llm=llm)

        result = await runner.compare(
            test_prompt="New prompt",
            production_prompt="Old prompt",
            test_messages=[{"role": "user", "content": "Hi"}],
        )

        assert isinstance(result, ComparisonRun)
        assert result.test_result.content in ("test output", "prod output")
        assert result.production_result is not None
        assert result.production_result.content in ("test output", "prod output")

    async def test_compare_uses_both_prompts(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("reply")
        runner = PlaygroundRunner(llm=llm)

        await runner.compare(
            test_prompt="Prompt A",
            production_prompt="Prompt B",
            test_messages=[{"role": "user", "content": "Hi"}],
        )

        # Both prompts should have been sent
        assert len(llm.calls) == 2
        sys_prompts = [call["messages"][0]["content"] for call in llm.calls]
        assert "Prompt A" in sys_prompts
        assert "Prompt B" in sys_prompts


class TestPlaygroundRunSuitePasses:
    """run_suite() passes when expected_contains match."""

    async def test_suite_passes_matching_content(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("The capital of France is Paris.")
        runner = PlaygroundRunner(llm=llm)

        results = await runner.run_suite(
            system_prompt="You are a geography expert.",
            test_cases=[
                {"input": "What is the capital of France?", "expected_contains": ["paris"]},
            ],
        )

        assert len(results) == 1
        assert isinstance(results[0], CaseResult)
        assert results[0].passed is True
        assert results[0].actual_content == "The capital of France is Paris."


class TestPlaygroundRunSuiteFails:
    """run_suite() fails when expected_contains don't match."""

    async def test_suite_fails_non_matching_content(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("I don't know.")
        runner = PlaygroundRunner(llm=llm)

        results = await runner.run_suite(
            system_prompt="You are a geography expert.",
            test_cases=[
                {"input": "What is the capital of France?", "expected_contains": ["paris"]},
            ],
        )

        assert len(results) == 1
        assert results[0].passed is False

    async def test_suite_partial_match_fails(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Paris is nice.")
        runner = PlaygroundRunner(llm=llm)

        results = await runner.run_suite(
            system_prompt="sys",
            test_cases=[
                {"input": "test", "expected_contains": ["paris", "london"]},
            ],
        )

        assert results[0].passed is False


class TestPlaygroundRunSuiteEmptyExpected:
    """run_suite() with empty expected_contains always passes."""

    async def test_empty_expected_always_passes(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("anything")
        runner = PlaygroundRunner(llm=llm)

        results = await runner.run_suite(
            system_prompt="sys",
            test_cases=[
                {"input": "hello", "expected_contains": []},
                {"input": "world"},
            ],
        )

        assert len(results) == 2
        assert all(r.passed for r in results)


class TestPlaygroundRunSuiteMultipleCases:
    """run_suite() processes multiple test cases sequentially."""

    async def test_multiple_test_cases(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Default fake response")
        runner = PlaygroundRunner(llm=llm)

        results = await runner.run_suite(
            system_prompt="sys",
            test_cases=[
                {"input": "a"},
                {"input": "b"},
                {"input": "c"},
            ],
        )

        assert len(results) == 3
        assert all(r.passed for r in results)
        assert results[0].input_text == "a"
        assert results[1].input_text == "b"
        assert results[2].input_text == "c"


class TestPlaygroundRunSendsSystemPromptFirst:
    """run() prepends the system prompt as the first message."""

    async def test_system_prompt_is_first_message(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        runner = PlaygroundRunner(llm=llm)

        await runner.run(
            system_prompt="Be concise.",
            test_messages=[{"role": "user", "content": "Hi"}],
        )

        assert len(llm.calls) == 1
        messages = llm.calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be concise."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Hi"


# ── API route tests ──────────────────────────────────────────────────

AUTH_HEADER = {"Authorization": "Bearer sk-test"}
VIEWER_HEADER = {"Authorization": "Bearer sk-viewer"}


@pytest.fixture
def playground_app() -> FastAPI:
    """Create a FastAPI app with playground routes and a real Container."""
    from stronghold.api.routes.playground import router as playground_router

    app = FastAPI()
    app.include_router(playground_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("Playground response")

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
        permissions={"admin": ["*"], "viewer": ["web_search"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()

    async def setup() -> Container:
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
            permission_table=PermissionTable.from_config(
                {"admin": ["*"], "viewer": ["web_search"]}
            ),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
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


class TestPlaygroundRunRoute:
    """POST /v1/stronghold/playground/run returns 200 for admin."""

    def test_run_returns_200(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/run",
                json={
                    "system_prompt": "You are helpful.",
                    "test_messages": [{"role": "user", "content": "Hi"}],
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "content" in data
            assert data["content"] == "Playground response"
            assert "latency_ms" in data
            assert "input_tokens" in data
            assert "output_tokens" in data

    def test_run_with_model(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/run",
                json={
                    "system_prompt": "sys",
                    "test_messages": [{"role": "user", "content": "test"}],
                    "model": "gpt-4",
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            assert resp.json()["model"] == "gpt-4"

    def test_run_requires_system_prompt(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/run",
                json={
                    "test_messages": [{"role": "user", "content": "Hi"}],
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400


class TestPlaygroundRunRouteAuth:
    """POST /v1/stronghold/playground/run requires admin (403)."""

    def test_unauthenticated_returns_401(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/run",
                json={
                    "system_prompt": "sys",
                    "test_messages": [{"role": "user", "content": "Hi"}],
                },
            )
            assert resp.status_code == 401


class TestPlaygroundCompareRoute:
    """POST /v1/stronghold/playground/compare — side-by-side."""

    def test_compare_returns_200(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/compare",
                json={
                    "test_prompt": "New prompt",
                    "production_prompt": "Old prompt",
                    "test_messages": [{"role": "user", "content": "Hi"}],
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "test_result" in data
            assert "production_result" in data
            # FakeLLMClient returns "Playground response" then "Default fake response"
            assert data["test_result"]["content"] != ""
            assert data["production_result"]["content"] != ""

    def test_compare_requires_test_prompt(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/compare",
                json={
                    "production_prompt": "Old prompt",
                    "test_messages": [{"role": "user", "content": "Hi"}],
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400

    def test_compare_unauthenticated_returns_401(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/compare",
                json={
                    "test_prompt": "New",
                    "production_prompt": "Old",
                    "test_messages": [{"role": "user", "content": "Hi"}],
                },
            )
            assert resp.status_code == 401


class TestPlaygroundSuiteRoute:
    """POST /v1/stronghold/playground/suite — batch test cases."""

    def test_suite_returns_200(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/suite",
                json={
                    "system_prompt": "You are helpful.",
                    "test_cases": [
                        {"input": "Hi", "expected_contains": ["response"]},
                        {"input": "Bye"},
                    ],
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "results" in data
            assert len(data["results"]) == 2
            assert data["results"][0]["passed"] is True
            assert data["results"][1]["passed"] is True

    def test_suite_requires_system_prompt(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/suite",
                json={
                    "test_cases": [{"input": "Hi"}],
                },
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 400

    def test_suite_unauthenticated_returns_401(self, playground_app: FastAPI) -> None:
        with TestClient(playground_app) as client:
            resp = client.post(
                "/v1/stronghold/playground/suite",
                json={
                    "system_prompt": "sys",
                    "test_cases": [{"input": "Hi"}],
                },
            )
            assert resp.status_code == 401
