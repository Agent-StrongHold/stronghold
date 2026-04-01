"""Tests for GitAgentExporter: serialize running agent to directory."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.exporter import GitAgentExporter
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.fakes import FakeLLMClient


@pytest.fixture
def store_with_agent() -> InMemoryAgentStore:
    """Create an InMemoryAgentStore with one pre-existing agent."""
    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")
    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()

    identity = AgentIdentity(
        name="test-agent",
        version="2.0.0",
        description="A test agent for export.",
        soul_prompt_name="agent.test-agent.soul",
        model="gpt-4o",
        model_fallbacks=("gemini-2.5-pro", "mistral-large"),
        model_constraints={"temperature": 0.3, "max_tokens": 4096},
        tools=("file_ops", "shell", "run_pytest"),
        rules=("Never break prod", "Always write tests"),
        trust_tier="t1",
        max_tool_rounds=10,
        reasoning_strategy="react",
        memory_config={"learnings": True, "episodic": True, "scope": "agent"},
        org_id="org-secret-123",
    )

    agent = Agent(
        identity=identity,
        strategy=DirectStrategy(),
        llm=fake_llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    agents: dict[str, Agent] = {"test-agent": agent}
    store = InMemoryAgentStore(agents, prompts)
    store._souls["test-agent"] = "You are a test agent.\n\nYou help with testing."
    store._rules["test-agent"] = "- Never break prod\n- Always write tests"
    return store


@pytest.fixture
def store_no_rules() -> InMemoryAgentStore:
    """Create a store with an agent that has no rules and no rules content."""
    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")
    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()

    identity = AgentIdentity(
        name="minimal-agent",
        version="1.0.0",
        description="Minimal agent.",
        soul_prompt_name="agent.minimal-agent.soul",
        model="auto",
    )

    agent = Agent(
        identity=identity,
        strategy=DirectStrategy(),
        llm=fake_llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    agents: dict[str, Agent] = {"minimal-agent": agent}
    store = InMemoryAgentStore(agents, prompts)
    store._souls["minimal-agent"] = "You are minimal."
    return store


class TestExportCreatesDirectory:
    """Tests that export_agent creates proper directory structure."""

    async def test_creates_agent_directory(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        assert result.is_dir()
        assert result.name == "test-agent"

    async def test_writes_agent_yaml(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        yaml_path = result / "agent.yaml"
        assert yaml_path.exists()
        manifest = yaml.safe_load(yaml_path.read_text())
        assert manifest["name"] == "test-agent"
        assert manifest["spec_version"] == "0.1.0"

    async def test_writes_soul_md(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        soul_path = result / "SOUL.md"
        assert soul_path.exists()
        assert soul_path.read_text() == "You are a test agent.\n\nYou help with testing."

    async def test_writes_rules_md_when_present(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        rules_path = result / "RULES.md"
        assert rules_path.exists()
        assert rules_path.read_text() == "- Never break prod\n- Always write tests"

    async def test_no_rules_md_when_absent(
        self, store_no_rules: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_no_rules)
        result = await exporter.export_agent("minimal-agent", tmp_path, org_id="")
        rules_path = result / "RULES.md"
        assert not rules_path.exists()


class TestManifestContent:
    """Tests that agent.yaml contains correct and complete data."""

    async def test_manifest_has_all_fields(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        manifest = yaml.safe_load((result / "agent.yaml").read_text())

        assert manifest["spec_version"] == "0.1.0"
        assert manifest["name"] == "test-agent"
        assert manifest["version"] == "2.0.0"
        assert manifest["description"] == "A test agent for export."
        assert manifest["soul"] == "SOUL.md"
        assert manifest["model"] == "gpt-4o"
        assert manifest["model_fallbacks"] == ["gemini-2.5-pro", "mistral-large"]
        assert manifest["model_constraints"] == {"temperature": 0.3, "max_tokens": 4096}
        assert manifest["tools"] == ["file_ops", "run_pytest", "shell"]  # sorted
        assert manifest["trust_tier"] == "t1"
        assert manifest["memory"] == {"episodic": True, "learnings": True, "scope": "agent"}
        assert manifest["reasoning"]["strategy"] == "react"
        assert manifest["reasoning"]["max_rounds"] == 10
        assert manifest["rules"] == ["Always write tests", "Never break prod"]  # sorted

    async def test_manifest_keys_sorted(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        """Verify YAML output has sorted keys for deterministic output."""
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        text = (result / "agent.yaml").read_text()
        # Parse and re-dump with sort_keys — should be identical
        parsed = yaml.safe_load(text)
        re_dumped = yaml.dump(parsed, default_flow_style=False, sort_keys=True)
        assert text == re_dumped


class TestRedaction:
    """Tests that sensitive data is stripped from exported data."""

    async def test_org_id_not_in_manifest(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        manifest = yaml.safe_load((result / "agent.yaml").read_text())
        assert "org_id" not in manifest
        text = (result / "agent.yaml").read_text()
        assert "org-secret-123" not in text

    async def test_internal_fields_not_in_manifest(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        manifest = yaml.safe_load((result / "agent.yaml").read_text())
        # These are internal AgentIdentity fields, not part of GitAgent format
        assert "soul_prompt_name" not in manifest
        assert "provenance" not in manifest
        assert "ai_reviewed" not in manifest
        assert "ai_review_clean" not in manifest
        assert "admin_reviewed" not in manifest
        assert "admin_reviewed_by" not in manifest
        assert "user_reviewed" not in manifest
        assert "active" not in manifest
        assert "delegation_mode" not in manifest

    async def test_api_key_pattern_redacted_from_soul(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        """If soul text accidentally contains an API key pattern, it's redacted."""
        store_with_agent._souls["test-agent"] = (
            "Use this key: sk-proj-abc123xyz456 to authenticate."
        )
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        soul_text = (result / "SOUL.md").read_text()
        assert "sk-proj-abc123xyz456" not in soul_text
        assert "[REDACTED]" in soul_text


class TestErrorHandling:
    """Tests for error conditions."""

    async def test_nonexistent_agent_raises(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        with pytest.raises(ValueError, match="not found"):
            await exporter.export_agent("nonexistent", tmp_path, org_id="org-1")

    async def test_returns_path_object(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        assert isinstance(result, Path)
        assert result == tmp_path / "test-agent"


class TestDeterministicOutput:
    """Tests that output is deterministic across multiple exports."""

    async def test_two_exports_produce_identical_output(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        dir1 = tmp_path / "run1"
        dir1.mkdir()
        dir2 = tmp_path / "run2"
        dir2.mkdir()

        result1 = await exporter.export_agent("test-agent", dir1, org_id="org-secret-123")
        result2 = await exporter.export_agent("test-agent", dir2, org_id="org-secret-123")

        # Compare all files
        for fname in ("agent.yaml", "SOUL.md", "RULES.md"):
            f1 = result1 / fname
            f2 = result2 / fname
            assert f1.exists() == f2.exists(), f"{fname} existence mismatch"
            if f1.exists():
                assert f1.read_text() == f2.read_text(), f"{fname} content mismatch"

    async def test_tools_sorted_in_manifest(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        manifest = yaml.safe_load((result / "agent.yaml").read_text())
        tools = manifest["tools"]
        assert tools == sorted(tools)

    async def test_memory_config_keys_sorted(
        self, store_with_agent: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_with_agent)
        result = await exporter.export_agent("test-agent", tmp_path, org_id="org-secret-123")
        manifest = yaml.safe_load((result / "agent.yaml").read_text())
        memory_keys = list(manifest["memory"].keys())
        assert memory_keys == sorted(memory_keys)


class TestMinimalAgent:
    """Tests export of a minimal agent with defaults."""

    async def test_minimal_agent_exports_cleanly(
        self, store_no_rules: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_no_rules)
        result = await exporter.export_agent("minimal-agent", tmp_path, org_id="")
        assert (result / "agent.yaml").exists()
        assert (result / "SOUL.md").exists()
        manifest = yaml.safe_load((result / "agent.yaml").read_text())
        assert manifest["name"] == "minimal-agent"
        assert manifest["version"] == "1.0.0"
        assert manifest["model"] == "auto"
        # Empty lists/dicts should still appear for clarity
        assert manifest["tools"] == []

    async def test_minimal_agent_no_optional_sections(
        self, store_no_rules: InMemoryAgentStore, tmp_path: Path
    ) -> None:
        exporter = GitAgentExporter(store_no_rules)
        result = await exporter.export_agent("minimal-agent", tmp_path, org_id="")
        manifest = yaml.safe_load((result / "agent.yaml").read_text())
        # model_fallbacks and model_constraints omitted when empty
        assert "model_fallbacks" not in manifest
        assert "model_constraints" not in manifest
        assert "sub_agents" not in manifest
        assert "rules" not in manifest
