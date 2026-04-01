"""Tests for GitAgentImporter: load agent definitions from directories."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest
import yaml

from stronghold.agents.importer import GitAgentImporter
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.types.agent import AgentIdentity


def _write_agent_yaml(path: Path, manifest: dict[str, object]) -> None:
    """Write an agent.yaml file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(manifest, default_flow_style=False))


def _write_file(path: Path, content: str) -> None:
    """Write a text file, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _minimal_manifest(name: str = "test-agent", **overrides: object) -> dict[str, object]:
    """Return a minimal valid agent.yaml manifest."""
    m: dict[str, object] = {
        "spec_version": "0.1.0",
        "name": name,
        "version": "1.0.0",
        "description": "A test agent",
        "reasoning": {"strategy": "direct", "max_rounds": 3},
        "model": "auto",
        "tools": ["web_search"],
    }
    m.update(overrides)
    return m


@pytest.fixture
def prompt_manager() -> InMemoryPromptManager:
    return InMemoryPromptManager()


@pytest.fixture
def importer(prompt_manager: InMemoryPromptManager) -> GitAgentImporter:
    return GitAgentImporter(prompt_manager=prompt_manager)


# ── Basic import ──────────────────────────────────────────────────────


class TestBasicImport:
    async def test_import_agent_returns_identity(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Import a valid agent directory and get back an AgentIdentity."""
        agent_dir = tmp_path / "test-agent"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest())
        _write_file(agent_dir / "SOUL.md", "You are a test agent.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert isinstance(result, AgentIdentity)
        assert result.name == "test-agent"
        assert result.version == "1.0.0"
        assert result.description == "A test agent"
        assert result.org_id == "org-1"

    async def test_import_parses_reasoning_fields(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Reasoning strategy and max_tool_rounds come from agent.yaml."""
        agent_dir = tmp_path / "my-agent"
        manifest = _minimal_manifest(
            name="my-agent",
            reasoning={"strategy": "react", "max_rounds": 7},
        )
        _write_agent_yaml(agent_dir / "agent.yaml", manifest)
        _write_file(agent_dir / "SOUL.md", "Soul content.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert result.reasoning_strategy == "react"
        assert result.max_tool_rounds == 7

    async def test_import_parses_tools(self, importer: GitAgentImporter, tmp_path: Path) -> None:
        """Tools list from manifest becomes a tuple on AgentIdentity."""
        agent_dir = tmp_path / "tooled"
        manifest = _minimal_manifest(name="tooled", tools=["shell", "git", "file_ops"])
        _write_agent_yaml(agent_dir / "agent.yaml", manifest)
        _write_file(agent_dir / "SOUL.md", "Soul.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert result.tools == ("shell", "git", "file_ops")

    async def test_import_parses_model_fields(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Model, model_fallbacks, and model_constraints from manifest."""
        agent_dir = tmp_path / "modeled"
        manifest = _minimal_manifest(
            name="modeled",
            model="gpt-4o",
            model_fallbacks=["gemini-2.5-pro", "mistral-large"],
            model_constraints={"temperature": 0.3, "max_tokens": 8192},
        )
        _write_agent_yaml(agent_dir / "agent.yaml", manifest)
        _write_file(agent_dir / "SOUL.md", "Soul.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert result.model == "gpt-4o"
        assert result.model_fallbacks == ("gemini-2.5-pro", "mistral-large")
        assert result.model_constraints == {"temperature": 0.3, "max_tokens": 8192}

    async def test_import_parses_memory_config(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Memory config dict from manifest lands on AgentIdentity."""
        agent_dir = tmp_path / "mem-agent"
        manifest = _minimal_manifest(
            name="mem-agent",
            memory={"learnings": True, "episodic": False, "scope": "agent"},
        )
        _write_agent_yaml(agent_dir / "agent.yaml", manifest)
        _write_file(agent_dir / "SOUL.md", "Soul.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert result.memory_config == {"learnings": True, "episodic": False, "scope": "agent"}


# ── Soul and rules prompts ────────────────────────────────────────────


class TestPromptStorage:
    async def test_soul_stored_as_prompt(
        self, importer: GitAgentImporter, prompt_manager: InMemoryPromptManager, tmp_path: Path
    ) -> None:
        """SOUL.md content is stored via prompt_manager under agent.{name}.soul."""
        agent_dir = tmp_path / "soul-agent"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="soul-agent"))
        _write_file(agent_dir / "SOUL.md", "You are the soul agent.\nBe wise.")

        await importer.import_agent(agent_dir, org_id="org-1")

        stored = await prompt_manager.get("agent.soul-agent.soul")
        assert stored == "You are the soul agent.\nBe wise."

    async def test_rules_stored_as_prompt(
        self, importer: GitAgentImporter, prompt_manager: InMemoryPromptManager, tmp_path: Path
    ) -> None:
        """RULES.md content is stored via prompt_manager under agent.{name}.rules."""
        agent_dir = tmp_path / "rules-agent"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="rules-agent"))
        _write_file(agent_dir / "SOUL.md", "Soul content.")
        _write_file(agent_dir / "RULES.md", "- Never do X\n- Always do Y")

        await importer.import_agent(agent_dir, org_id="org-1")

        stored = await prompt_manager.get("agent.rules-agent.rules")
        assert stored == "- Never do X\n- Always do Y"

    async def test_no_rules_file_skips_rules_prompt(
        self, importer: GitAgentImporter, prompt_manager: InMemoryPromptManager, tmp_path: Path
    ) -> None:
        """When RULES.md is absent, no rules prompt is stored."""
        agent_dir = tmp_path / "no-rules"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="no-rules"))
        _write_file(agent_dir / "SOUL.md", "Soul content.")

        await importer.import_agent(agent_dir, org_id="org-1")

        stored = await prompt_manager.get("agent.no-rules.rules")
        assert stored == ""


# ── Trust tier override ───────────────────────────────────────────────


class TestTrustTier:
    async def test_default_trust_tier_is_t2(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Default trust_tier is t2 when not specified."""
        agent_dir = tmp_path / "tier-agent"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="tier-agent"))
        _write_file(agent_dir / "SOUL.md", "Soul.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert result.trust_tier == "t2"

    async def test_trust_tier_override(self, importer: GitAgentImporter, tmp_path: Path) -> None:
        """Caller can override trust_tier."""
        agent_dir = tmp_path / "tier-override"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="tier-override"))
        _write_file(agent_dir / "SOUL.md", "Soul.")

        result = await importer.import_agent(agent_dir, org_id="org-1", trust_tier="t3")

        assert result.trust_tier == "t3"

    async def test_manifest_trust_tier_ignored(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """trust_tier in agent.yaml is IGNORED for security -- caller decides."""
        agent_dir = tmp_path / "sneaky"
        manifest = _minimal_manifest(name="sneaky", trust_tier="t0")
        _write_agent_yaml(agent_dir / "agent.yaml", manifest)
        _write_file(agent_dir / "SOUL.md", "Soul.")

        result = await importer.import_agent(agent_dir, org_id="org-1")

        assert result.trust_tier == "t2"  # default, not t0 from manifest


# ── Validation ────────────────────────────────────────────────────────


class TestValidation:
    async def test_missing_agent_yaml_raises(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Raises FileNotFoundError when agent.yaml is missing."""
        agent_dir = tmp_path / "no-yaml"
        agent_dir.mkdir()
        _write_file(agent_dir / "SOUL.md", "Soul.")

        with pytest.raises(FileNotFoundError, match="agent.yaml"):
            await importer.import_agent(agent_dir, org_id="org-1")

    async def test_missing_soul_md_raises(self, importer: GitAgentImporter, tmp_path: Path) -> None:
        """Raises FileNotFoundError when SOUL.md is missing."""
        agent_dir = tmp_path / "no-soul"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="no-soul"))

        with pytest.raises(FileNotFoundError, match="SOUL.md"):
            await importer.import_agent(agent_dir, org_id="org-1")

    async def test_missing_name_in_yaml_raises(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Raises ValueError when agent.yaml has no 'name' field."""
        agent_dir = tmp_path / "bad-yaml"
        manifest = {"spec_version": "0.1.0", "description": "no name"}
        _write_agent_yaml(agent_dir / "agent.yaml", manifest)
        _write_file(agent_dir / "SOUL.md", "Soul.")

        with pytest.raises(ValueError, match="name"):
            await importer.import_agent(agent_dir, org_id="org-1")

    async def test_nonexistent_directory_raises(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Raises FileNotFoundError for a path that doesn't exist."""
        agent_dir = tmp_path / "ghost"

        with pytest.raises(FileNotFoundError):
            await importer.import_agent(agent_dir, org_id="org-1")


# ── Idempotent re-import ─────────────────────────────────────────────


class TestIdempotentReimport:
    async def test_reimport_updates_identity(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Re-importing the same agent updates rather than duplicating."""
        agent_dir = tmp_path / "idempotent"
        _write_agent_yaml(
            agent_dir / "agent.yaml",
            _minimal_manifest(name="idempotent", description="v1"),
        )
        _write_file(agent_dir / "SOUL.md", "Soul v1.")

        first = await importer.import_agent(agent_dir, org_id="org-1")
        assert first.description == "v1"

        # Update manifest and soul, re-import
        _write_agent_yaml(
            agent_dir / "agent.yaml",
            _minimal_manifest(name="idempotent", description="v2", version="2.0.0"),
        )
        _write_file(agent_dir / "SOUL.md", "Soul v2.")

        second = await importer.import_agent(agent_dir, org_id="org-1")
        assert second.description == "v2"
        assert second.version == "2.0.0"

    async def test_reimport_updates_soul_prompt(
        self,
        importer: GitAgentImporter,
        prompt_manager: InMemoryPromptManager,
        tmp_path: Path,
    ) -> None:
        """Re-import updates the soul prompt content."""
        agent_dir = tmp_path / "re-soul"
        _write_agent_yaml(agent_dir / "agent.yaml", _minimal_manifest(name="re-soul"))
        _write_file(agent_dir / "SOUL.md", "Original soul.")

        await importer.import_agent(agent_dir, org_id="org-1")
        assert await prompt_manager.get("agent.re-soul.soul") == "Original soul."

        _write_file(agent_dir / "SOUL.md", "Updated soul.")
        await importer.import_agent(agent_dir, org_id="org-1")
        assert await prompt_manager.get("agent.re-soul.soul") == "Updated soul."


# ── Sub-agent recursion ──────────────────────────────────────────────


class TestSubAgentRecursion:
    async def test_imports_sub_agents_from_agents_dir(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """An agents/ subdirectory triggers recursive import of sub-agents."""
        parent = tmp_path / "parent-agent"
        _write_agent_yaml(parent / "agent.yaml", _minimal_manifest(name="parent-agent"))
        _write_file(parent / "SOUL.md", "Parent soul.")

        # Create two sub-agents
        child1 = parent / "agents" / "child-one"
        _write_agent_yaml(child1 / "agent.yaml", _minimal_manifest(name="child-one"))
        _write_file(child1 / "SOUL.md", "Child one soul.")

        child2 = parent / "agents" / "child-two"
        _write_agent_yaml(child2 / "agent.yaml", _minimal_manifest(name="child-two"))
        _write_file(child2 / "SOUL.md", "Child two soul.")

        result = await importer.import_agent(parent, org_id="org-1")

        # Parent imported
        assert result.name == "parent-agent"

        # Sub-agents also imported
        assert "child-one" in importer.imported
        assert "child-two" in importer.imported
        assert importer.imported["child-one"].org_id == "org-1"

    async def test_nested_sub_agents_recursive(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Sub-agents with their own agents/ subdirectory trigger deeper recursion."""
        root = tmp_path / "root-agent"
        _write_agent_yaml(root / "agent.yaml", _minimal_manifest(name="root-agent"))
        _write_file(root / "SOUL.md", "Root soul.")

        mid = root / "agents" / "mid-agent"
        _write_agent_yaml(mid / "agent.yaml", _minimal_manifest(name="mid-agent"))
        _write_file(mid / "SOUL.md", "Mid soul.")

        leaf = mid / "agents" / "leaf-agent"
        _write_agent_yaml(leaf / "agent.yaml", _minimal_manifest(name="leaf-agent"))
        _write_file(leaf / "SOUL.md", "Leaf soul.")

        await importer.import_agent(root, org_id="org-1")

        assert "root-agent" in importer.imported
        assert "mid-agent" in importer.imported
        assert "leaf-agent" in importer.imported

    async def test_sub_agents_inherit_org_id_and_trust_tier(
        self, importer: GitAgentImporter, tmp_path: Path
    ) -> None:
        """Sub-agents get the same org_id and trust_tier as the parent import call."""
        parent = tmp_path / "inheritor"
        _write_agent_yaml(parent / "agent.yaml", _minimal_manifest(name="inheritor"))
        _write_file(parent / "SOUL.md", "Parent.")

        child = parent / "agents" / "child-inherit"
        _write_agent_yaml(child / "agent.yaml", _minimal_manifest(name="child-inherit"))
        _write_file(child / "SOUL.md", "Child.")

        await importer.import_agent(parent, org_id="org-5", trust_tier="t3")

        assert importer.imported["inheritor"].org_id == "org-5"
        assert importer.imported["inheritor"].trust_tier == "t3"
        assert importer.imported["child-inherit"].org_id == "org-5"
        assert importer.imported["child-inherit"].trust_tier == "t3"

    async def test_sub_agents_soul_prompts_stored(
        self,
        importer: GitAgentImporter,
        prompt_manager: InMemoryPromptManager,
        tmp_path: Path,
    ) -> None:
        """Sub-agent SOUL.md files are stored as prompts."""
        parent = tmp_path / "prompt-parent"
        _write_agent_yaml(parent / "agent.yaml", _minimal_manifest(name="prompt-parent"))
        _write_file(parent / "SOUL.md", "Parent soul.")

        child = parent / "agents" / "prompt-child"
        _write_agent_yaml(child / "agent.yaml", _minimal_manifest(name="prompt-child"))
        _write_file(child / "SOUL.md", "Child soul content.")

        await importer.import_agent(parent, org_id="org-1")

        assert await prompt_manager.get("agent.prompt-parent.soul") == "Parent soul."
        assert await prompt_manager.get("agent.prompt-child.soul") == "Child soul content."
