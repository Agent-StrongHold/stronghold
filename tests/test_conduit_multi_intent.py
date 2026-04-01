"""Tests for multi-intent parallel dispatch in the Conduit pipeline.

Covers: multi-intent detection, parallel dispatch via asyncio.gather,
result aggregation, partial failure handling, single-intent passthrough,
session stickiness bypass, and response format.

Uses real classes + FakeLLMClient. No unittest.mock.
"""

from __future__ import annotations

from typing import Any

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
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
from stronghold.types.auth import AuthContext, IdentityKind, PermissionTable
from stronghold.types.config import (
    RoutingConfig,
    SecurityConfig,
    SessionsConfig,
    StrongholdConfig,
    TaskTypeConfig,
)
from tests.fakes import FakeLLMClient

_TEST_AUTH = AuthContext(
    user_id="test-user",
    username="test-user",
    org_id="test-org",
    roles=frozenset({"user"}),
    kind=IdentityKind.USER,
    auth_method="test",
)


def _build_config() -> StrongholdConfig:
    return StrongholdConfig(
        providers={
            "test_provider": {
                "status": "active",
                "billing_cycle": "monthly",
                "free_tokens": 1_000_000_000,
            },
        },
        models={
            "test-medium": {
                "provider": "test_provider",
                "tier": "medium",
                "quality": 0.6,
                "speed": 500,
                "litellm_id": "test/medium",
                "strengths": ["code", "reasoning"],
            },
            "test-small": {
                "provider": "test_provider",
                "tier": "small",
                "quality": 0.4,
                "speed": 1000,
                "litellm_id": "test/small",
                "strengths": ["chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(
                keywords=["hello", "hi", "hey", "thanks"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug", "error", "implement", "class", "module"],
                min_tier="medium",
                preferred_strengths=["code"],
            ),
            "automation": TaskTypeConfig(
                keywords=["light", "fan", "turn on", "turn off"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
            "search": TaskTypeConfig(
                keywords=["search", "look up", "find"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
        },
        routing=RoutingConfig(),
        sessions=SessionsConfig(),
        security=SecurityConfig(),
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )


async def _build_container(
    *,
    llm: FakeLLMClient | None = None,
    intent_registry: IntentRegistry | None = None,
) -> Container:
    llm = llm or FakeLLMClient()
    config = _build_config()
    prompt_manager = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    context_builder = ContextBuilder()
    warden = Warden()
    quota_tracker = InMemoryQuotaTracker()
    session_store = InMemorySessionStore()
    tracer = NoopTracingBackend()

    await prompt_manager.upsert("agent.arbiter.soul", "You are the Arbiter.", label="production")
    await prompt_manager.upsert(
        "agent.artificer.soul", "You are the Artificer, code specialist.", label="production"
    )
    await prompt_manager.upsert(
        "agent.ranger.soul", "You are the Ranger, search specialist.", label="production"
    )
    await prompt_manager.upsert(
        "agent.warden-at-arms.soul",
        "You are the Warden-at-Arms, automation specialist.",
        label="production",
    )

    arbiter_agent = Agent(
        identity=AgentIdentity(name="arbiter", soul_prompt_name="agent.arbiter.soul", model="auto"),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompt_manager,
        warden=warden,
        session_store=session_store,
        tracer=tracer,
    )

    artificer_agent = Agent(
        identity=AgentIdentity(
            name="artificer",
            soul_prompt_name="agent.artificer.soul",
            model="auto",
            reasoning_strategy="direct",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompt_manager,
        warden=warden,
        session_store=session_store,
        tracer=tracer,
    )

    ranger_agent = Agent(
        identity=AgentIdentity(
            name="ranger",
            soul_prompt_name="agent.ranger.soul",
            model="auto",
            reasoning_strategy="direct",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompt_manager,
        warden=warden,
        session_store=session_store,
        tracer=tracer,
    )

    warden_at_arms_agent = Agent(
        identity=AgentIdentity(
            name="warden-at-arms",
            soul_prompt_name="agent.warden-at-arms.soul",
            model="auto",
            reasoning_strategy="direct",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompt_manager,
        warden=warden,
        session_store=session_store,
        tracer=tracer,
    )

    agents: dict[str, Agent] = {
        "arbiter": arbiter_agent,
        "artificer": artificer_agent,
        "ranger": ranger_agent,
        "warden-at-arms": warden_at_arms_agent,
    }

    audit_log = InMemoryAuditLog()
    perm_table = PermissionTable.from_config(config.permissions)

    return Container(
        config=config,
        auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
        permission_table=perm_table,
        router=RouterEngine(quota_tracker),
        classifier=ClassifierEngine(),
        quota_tracker=quota_tracker,
        prompt_manager=prompt_manager,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=session_store,
        audit_log=audit_log,
        warden=warden,
        gate=Gate(warden=warden),
        sentinel=Sentinel(
            warden=warden,
            permission_table=perm_table,
            audit_log=audit_log,
        ),
        tracer=tracer,
        context_builder=context_builder,
        intent_registry=intent_registry or IntentRegistry(),
        llm=llm,
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        agents=agents,
    )


class TestMultiIntentDetection:
    """Multi-intent is detected and routed to parallel dispatch."""

    async def test_multi_intent_detected_returns_combined_response(self) -> None:
        """Compound request with two distinct intents yields aggregated output."""
        llm = FakeLLMClient()
        # Two calls: one for code subtask, one for search subtask
        llm.set_responses(
            _chat_response("Here is the code fix."),
            _chat_response("Search results for Python docs."),
        )
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to parse JSON and also "
                        "search for the latest Python documentation"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        # Should be a multi-intent response
        assert result["_routing"]["intent"]["classified_by"] == "multi_intent"
        assert "sub_results" in result["_routing"]
        assert len(result["_routing"]["sub_results"]) >= 2

    async def test_multi_intent_response_contains_all_subtask_content(self) -> None:
        """Aggregated response content includes content from each subtask."""
        llm = FakeLLMClient()
        llm.set_responses(
            _chat_response("CODE_RESULT_ALPHA"),
            _chat_response("SEARCH_RESULT_BETA"),
        )
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to parse JSON and also "
                        "search for the latest Python documentation"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        content = result["choices"][0]["message"]["content"]
        assert "CODE_RESULT_ALPHA" in content
        assert "SEARCH_RESULT_BETA" in content

    async def test_multi_intent_sub_results_have_task_types(self) -> None:
        """Each sub-result records which task_type it handled."""
        llm = FakeLLMClient()
        llm.set_responses(
            _chat_response("code output"),
            _chat_response("search output"),
        )
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to implement sorting and also "
                        "search for algorithm benchmarks"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        sub_results = result["_routing"]["sub_results"]
        task_types = {sr["task_type"] for sr in sub_results}
        assert "code" in task_types
        assert "search" in task_types


class TestParallelDispatch:
    """Subtasks are dispatched concurrently via asyncio.gather."""

    async def test_parallel_dispatch_calls_multiple_agents(self) -> None:
        """Each detected intent dispatches to its registered agent."""
        llm = FakeLLMClient()
        llm.set_responses(
            _chat_response("code result"),
            _chat_response("automation result"),
        )
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to validate inputs and also turn on the living room light"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        sub_results = result["_routing"]["sub_results"]
        agents_used = {sr["agent"] for sr in sub_results}
        assert "artificer" in agents_used
        assert "warden-at-arms" in agents_used

    async def test_parallel_dispatch_uses_all_llm_calls(self) -> None:
        """LLM is called once per subtask (at minimum)."""
        llm = FakeLLMClient()
        llm.set_responses(
            _chat_response("r1"),
            _chat_response("r2"),
        )
        container = await _build_container(llm=llm)

        await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to sort data and also "
                        "search for sorting algorithm benchmarks"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        # At least 2 LLM calls (one per subtask)
        assert len(llm.calls) >= 2


class TestPartialFailure:
    """Partial failure: some subtasks fail but others succeed."""

    async def test_partial_failure_returns_successful_results(self) -> None:
        """If one subtask fails, the other still returns its content."""
        llm = _FailingOnNthCallLLM(fail_on_call=1)  # First subtask fails
        container = await _build_container(llm=llm)  # type: ignore[arg-type]

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to parse XML and also search for XML parsing libraries"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        # Should still return a response (not raise)
        assert result["object"] == "chat.completion"
        content = result["choices"][0]["message"]["content"]
        assert content  # Not empty

    async def test_partial_failure_records_error_in_sub_results(self) -> None:
        """Failed subtask is recorded with an error field in sub_results."""
        llm = _FailingOnNthCallLLM(fail_on_call=1)
        container = await _build_container(llm=llm)  # type: ignore[arg-type]

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to merge lists and also "
                        "search for list operation benchmarks"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        sub_results = result["_routing"]["sub_results"]
        errors = [sr for sr in sub_results if sr.get("error")]
        successes = [sr for sr in sub_results if not sr.get("error")]
        assert len(errors) >= 1
        assert len(successes) >= 1

    async def test_all_subtasks_fail_returns_error_response(self) -> None:
        """If all subtasks fail, still return a valid response with error info."""
        llm = _FailingOnNthCallLLM(fail_on_call=0)  # All calls fail
        container = await _build_container(llm=llm)  # type: ignore[arg-type]

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to sort arrays and also search for sorting benchmarks"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        assert result["object"] == "chat.completion"
        sub_results = result["_routing"]["sub_results"]
        assert all(sr.get("error") for sr in sub_results)


class TestSingleIntentUnchanged:
    """Single-intent messages bypass multi-intent logic entirely."""

    async def test_single_intent_goes_through_normal_path(self) -> None:
        """A plain chat message does not trigger multi-intent dispatch."""
        llm = FakeLLMClient()
        llm.set_simple_response("Hello there!")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hello how are you"}],
            auth=_TEST_AUTH,
        )

        assert result["_routing"]["agent"] == "arbiter"
        assert "sub_results" not in result["_routing"]

    async def test_single_code_intent_routes_normally(self) -> None:
        """A single code intent routes to artificer without multi-intent."""
        llm = FakeLLMClient()
        llm.set_simple_response("Here is the code.")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to validate email "
                        "addresses in utils.py and return True for valid ones"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        assert result["_routing"]["agent"] == "artificer"
        assert "sub_results" not in result["_routing"]


class TestMultiIntentResponseFormat:
    """The aggregated response follows OpenAI-compatible format."""

    async def test_response_has_openai_format(self) -> None:
        """Multi-intent response has id, object, model, choices, usage."""
        llm = FakeLLMClient()
        llm.set_responses(
            _chat_response("part 1"),
            _chat_response("part 2"),
        )
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to parse data and also "
                        "search for data parsing best practices"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        assert result["object"] == "chat.completion"
        assert "id" in result
        assert result["id"].startswith("stronghold-")
        assert "choices" in result
        assert len(result["choices"]) == 1
        assert result["choices"][0]["message"]["role"] == "assistant"
        assert "usage" in result

    async def test_response_id_includes_multi(self) -> None:
        """Multi-intent response ID indicates multi-intent dispatch."""
        llm = FakeLLMClient()
        llm.set_responses(
            _chat_response("code"),
            _chat_response("search"),
        )
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to compress files and also "
                        "search for compression algorithm comparisons"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )

        assert "multi" in result["id"]


class TestMultiIntentWithHint:
    """Intent hints bypass multi-intent detection."""

    async def test_hint_skips_multi_intent(self) -> None:
        """When an intent_hint is provided, multi-intent is not checked."""
        llm = FakeLLMClient()
        llm.set_simple_response("code only response")
        container = await _build_container(llm=llm)

        # The message would trigger multi-intent (code + search) but the hint
        # forces single-intent. Must also pass sufficiency for code: needs
        # what (function), where (.py file), how (return True).
        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function in parser.py to parse JSON "
                        "and also search for JSON libraries. Return True on success."
                    ),
                }
            ],
            auth=_TEST_AUTH,
            intent_hint="code",
        )

        # Hint forces single-intent path
        assert result["_routing"]["intent"]["classified_by"] == "hint"
        assert "sub_results" not in result["_routing"]


# ── Helpers ──────────────────────────────────────────────────────────


def _chat_response(content: str) -> dict[str, Any]:
    """Build a fake LLM chat completion response."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


class _SubtaskError(Exception):
    """Custom error that is NOT caught by Agent.handle() strategy recovery.

    Agent.handle() catches (ValueError, RuntimeError, TimeoutError, OSError).
    This exception type propagates through to _dispatch_subtask's except clause.
    """


class _FailingOnNthCallLLM:
    """LLM fake that raises on a specific call index, succeeds on others.

    If fail_on_call=0, ALL calls fail.
    If fail_on_call=1, the 1st call fails, subsequent calls succeed.

    Uses _SubtaskError which propagates through Agent.handle() because it
    is not in the caught exception tuple.
    """

    def __init__(self, fail_on_call: int = 0) -> None:
        self._fail_on_call = fail_on_call
        self._call_count = 0
        self.calls: list[dict[str, Any]] = []
        self._fallback_models: list[str] = []

    async def complete(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._call_count += 1
        self.calls.append({"messages": messages, "model": model, **kwargs})
        if self._fail_on_call == 0 or self._call_count == self._fail_on_call:
            msg = f"Simulated LLM failure on call {self._call_count}"
            raise _SubtaskError(msg)
        return _chat_response(f"Success from call {self._call_count}")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        **kwargs: Any,
    ) -> Any:
        yield 'data: {"choices":[{"delta":{"content":"fake stream"}}]}\n\n'
        yield "data: [DONE]\n\n"
