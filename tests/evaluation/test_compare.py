"""Tests for model comparison — side-by-side evaluation."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from stronghold.evaluation.compare import ComparisonResult, ModelComparator, ModelResult
from tests.fakes import FakeAuthProvider, FakeLLMClient

from stronghold.types.auth import AuthContext


# ── Unit Tests: ModelResult / ComparisonResult ─────────────────────


class TestModelResultDataclass:
    def test_defaults(self) -> None:
        r = ModelResult(model="gpt-4")
        assert r.model == "gpt-4"
        assert r.content == ""
        assert r.latency_ms == 0
        assert r.input_tokens == 0
        assert r.output_tokens == 0
        assert r.error == ""

    def test_error_result(self) -> None:
        r = ModelResult(model="gpt-4", error="timeout")
        assert r.error == "timeout"
        assert r.content == ""


class TestComparisonResultDataclass:
    def test_defaults(self) -> None:
        cr = ComparisonResult()
        assert cr.models == []
        assert cr.results == []
        assert cr.task_type == ""

    def test_has_correct_model_list(self) -> None:
        cr = ComparisonResult(
            models=["model-a", "model-b"],
            results=[
                ModelResult(model="model-a", content="hello"),
                ModelResult(model="model-b", content="world"),
            ],
            task_type="code",
        )
        assert cr.models == ["model-a", "model-b"]
        assert len(cr.results) == 2
        assert cr.task_type == "code"


# ── Unit Tests: ModelComparator ────────────────────────────────────


class TestCompare2Models:
    async def test_compare_returns_results_for_both(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("Answer A", model="model-a"),
            _make_response("Answer B", model="model-b"),
        )
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["model-a", "model-b"],
        )
        assert len(result.results) == 2
        assert result.models == ["model-a", "model-b"]
        contents = {r.model: r.content for r in result.results}
        assert "model-a" in contents
        assert "model-b" in contents

    async def test_task_type_propagated(self) -> None:
        llm = FakeLLMClient()
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["m1"],
            task_type="code",
        )
        assert result.task_type == "code"


class TestCompareWithError:
    async def test_error_model_included_in_results(self) -> None:
        llm = _ErrorLLM(fail_models={"bad-model"})
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["good-model", "bad-model"],
        )
        assert len(result.results) == 2
        errors = {r.model: r.error for r in result.results}
        assert errors["bad-model"] != ""
        assert errors["good-model"] == ""


class TestLatencyTracked:
    async def test_latency_is_positive(self) -> None:
        llm = FakeLLMClient()
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["model-a"],
        )
        # Latency should be non-negative (could be 0ms for fast fakes)
        assert result.results[0].latency_ms >= 0

    async def test_error_model_has_latency(self) -> None:
        llm = _ErrorLLM(fail_models={"bad"})
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["bad"],
        )
        assert result.results[0].latency_ms >= 0
        assert result.results[0].error != ""


class TestParallelExecution:
    async def test_both_models_called(self) -> None:
        """Both models should be called (parallel via gather)."""
        llm = FakeLLMClient()
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["model-a", "model-b"],
        )
        assert len(result.results) == 2
        called_models = [c["model"] for c in llm.calls]
        assert "model-a" in called_models
        assert "model-b" in called_models


class TestEmptyModelsList:
    async def test_empty_models_returns_empty_results(self) -> None:
        llm = FakeLLMClient()
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=[],
        )
        assert result.results == []
        assert result.models == []


class TestTokenUsage:
    async def test_tokens_extracted(self) -> None:
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("Answer", input_tokens=50, output_tokens=100),
        )
        comparator = ModelComparator(llm)
        result = await comparator.compare(
            messages=[{"role": "user", "content": "Hello"}],
            models=["m1"],
        )
        assert result.results[0].input_tokens == 50
        assert result.results[0].output_tokens == 100


# ── API Route Tests ────────────────────────────────────────────────


class TestCompareAPIRoute:
    def test_requires_auth_401(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/compare/models",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "models": ["a", "b"],
                },
            )
            assert resp.status_code == 401

    def test_requires_admin_403(self) -> None:
        app = _create_test_app(roles=frozenset({"user"}))
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/compare/models",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "models": ["a", "b"],
                },
                headers={"Authorization": "Bearer sk-test-key"},
            )
            assert resp.status_code == 403

    def test_returns_results(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/compare/models",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "models": ["model-a", "model-b"],
                },
                headers={"Authorization": "Bearer sk-test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["models"] == ["model-a", "model-b"]
            assert len(data["results"]) == 2

    def test_max_5_models_enforced(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/compare/models",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "models": ["m1", "m2", "m3", "m4", "m5", "m6"],
                },
                headers={"Authorization": "Bearer sk-test-key"},
            )
            assert resp.status_code == 400
            assert "5" in resp.json()["detail"]

    def test_empty_models_returns_empty(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/compare/models",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "models": [],
                },
                headers={"Authorization": "Bearer sk-test-key"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["results"] == []

    def test_task_type_in_response(self) -> None:
        app = _create_test_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/compare/models",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "models": ["m1"],
                    "task_type": "code",
                },
                headers={"Authorization": "Bearer sk-test-key"},
            )
            assert resp.status_code == 200
            assert resp.json()["task_type"] == "code"


# ── Helpers ────────────────────────────────────────────────────────


def _make_response(
    content: str,
    *,
    model: str = "fake-model",
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> dict[str, Any]:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


class _ErrorLLM:
    """LLM fake that raises for specific models."""

    def __init__(self, fail_models: set[str] | None = None) -> None:
        self._fail = fail_models or set()

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if model in self._fail:
            msg = f"Model {model} unavailable"
            raise RuntimeError(msg)
        return _make_response("ok", model=model)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> Any:
        yield 'data: {"choices":[{"delta":{"content":"fake"}}]}\n\n'


def _create_test_app(
    roles: frozenset[str] = frozenset({"admin", "user"}),
) -> Any:
    """Create a minimal FastAPI app with the compare route for testing."""
    from fastapi import FastAPI

    from stronghold.api.routes.compare import router as compare_router

    app = FastAPI()
    app.include_router(compare_router)

    # Wire a minimal container onto app.state
    llm = FakeLLMClient()
    auth_ctx = AuthContext(
        user_id="test-admin",
        username="admin",
        roles=roles,
        org_id="test-org",
        auth_method="api_key",
    )
    auth_provider = FakeAuthProvider(auth_context=auth_ctx)

    class _MinimalContainer:
        def __init__(self) -> None:
            self.auth_provider = auth_provider
            self.llm = llm

    app.state.container = _MinimalContainer()
    return app
