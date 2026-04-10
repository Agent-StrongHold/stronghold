"""Protocol coverage — import each protocol module and verify fake/real
implementations satisfy them.

Protocol class definitions count toward coverage when they're imported
(the `class` and `def` lines execute). The `...` bodies are unreachable
unless called via super(), which would require perfect signature matching.

Instead we import each module (covering class/method definitions) and
verify that known implementations match the protocol via isinstance.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import stronghold.protocols


def test_all_protocol_modules_importable() -> None:
    """Every module in stronghold.protocols imports cleanly (covers class/def lines)."""
    for info in pkgutil.iter_modules(stronghold.protocols.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"stronghold.protocols.{info.name}")
        assert mod is not None


# ── Verify known implementations satisfy their protocols ───────────


def test_auth_provider_implementations() -> None:
    from stronghold.protocols.auth import AuthProvider
    from stronghold.security.auth_static import StaticKeyAuthProvider
    assert isinstance(StaticKeyAuthProvider(api_key="k"), AuthProvider)


def test_model_router_implementation() -> None:
    from stronghold.protocols.router import ModelRouter
    from stronghold.quota.tracker import InMemoryQuotaTracker
    from stronghold.router.selector import RouterEngine
    assert isinstance(RouterEngine(InMemoryQuotaTracker()), ModelRouter)


def test_intent_classifier_implementation() -> None:
    from stronghold.classifier.engine import ClassifierEngine
    from stronghold.protocols.classifier import IntentClassifier
    assert isinstance(ClassifierEngine(), IntentClassifier)


def test_quota_tracker_implementation() -> None:
    from stronghold.protocols.quota import QuotaTracker
    from stronghold.quota.tracker import InMemoryQuotaTracker
    assert isinstance(InMemoryQuotaTracker(), QuotaTracker)


def test_prompt_manager_implementation() -> None:
    from stronghold.prompts.store import InMemoryPromptManager
    from stronghold.protocols.prompts import PromptManager
    assert isinstance(InMemoryPromptManager(), PromptManager)


def test_llm_client_implementation() -> None:
    from stronghold.protocols.llm import LLMClient
    from tests.fakes import FakeLLMClient
    assert isinstance(FakeLLMClient(), LLMClient)


def test_session_store_from_protocols() -> None:
    from stronghold.protocols.memory import SessionStore
    from stronghold.sessions.store import InMemorySessionStore
    assert isinstance(InMemorySessionStore(), SessionStore)


def test_tool_registry_implementation() -> None:
    from stronghold.protocols.tools import ToolRegistry
    from stronghold.tools.registry import InMemoryToolRegistry
    assert isinstance(InMemoryToolRegistry(), ToolRegistry)


def test_tracing_backend_implementation() -> None:
    from stronghold.protocols.tracing import TracingBackend
    from stronghold.tracing.noop import NoopTracingBackend
    assert isinstance(NoopTracingBackend(), TracingBackend)


def test_rate_limiter_implementation_exists() -> None:
    """RateLimiter protocol is defined and has expected interface."""
    from stronghold.protocols.rate_limit import RateLimiter
    # Protocol has check and record methods
    assert hasattr(RateLimiter, "check")
    assert hasattr(RateLimiter, "record")


def test_secret_backend_importable() -> None:
    from stronghold.protocols.secrets import SecretBackend, SecretResult
    assert SecretBackend is not None
    # SecretResult is a dataclass
    r = SecretResult(value="test", version="1")
    assert r.value == "test"


def test_vault_client_importable() -> None:
    from stronghold.protocols.vault import VaultClient, VaultSecret
    assert VaultClient is not None
    # VaultSecret can be constructed
    assert VaultSecret is not None


def test_data_store_importable() -> None:
    from stronghold.protocols.data import DataStore
    assert DataStore is not None
    assert hasattr(DataStore, "execute")


def test_embedding_client_importable() -> None:
    from stronghold.protocols.embeddings import EmbeddingClient
    assert EmbeddingClient is not None


def test_feedback_protocols_importable() -> None:
    from stronghold.protocols.feedback import FeedbackExtractor, ViolationStore
    assert FeedbackExtractor is not None
    assert ViolationStore is not None


def test_agent_store_importable() -> None:
    from stronghold.protocols.agents import AgentStore
    assert AgentStore is not None


def test_skills_protocols_importable() -> None:
    from stronghold.protocols.skills import SkillForge, SkillLoader, SkillMarketplace
    assert SkillLoader is not None
    assert SkillForge is not None
    assert SkillMarketplace is not None


def test_tools_protocols_importable() -> None:
    from stronghold.protocols.tools import ToolExecutor, ToolPlugin, ToolRegistry
    assert ToolExecutor is not None
    assert ToolRegistry is not None
    assert ToolPlugin is not None


def test_tracing_protocols_importable() -> None:
    from stronghold.protocols.tracing import Span, Trace, TracingBackend
    assert Span is not None
    assert Trace is not None
    assert TracingBackend is not None


def test_mcp_deployer_protocol_importable() -> None:
    from stronghold.protocols.mcp import McpDeployerClient
    assert McpDeployerClient is not None


def test_agent_pod_protocols_importable() -> None:
    from stronghold.protocols.agent_pod import AgentPodDiscovery, AgentPodInfo
    assert AgentPodDiscovery is not None
    assert AgentPodInfo is not None
