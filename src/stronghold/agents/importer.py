"""GitAgent directory import.

Reads agent definitions from a directory structure:
  agent-name/
  ├── agent.yaml     # Manifest (spec_version, name, version, reasoning, model, tools)
  ├── SOUL.md        # System prompt (required)
  ├── RULES.md       # Hard constraints (optional)
  └── agents/        # Sub-agent directories (optional, recursive)
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Any

import yaml

from stronghold.types.agent import AgentIdentity

if TYPE_CHECKING:
    from stronghold.prompts.store import InMemoryPromptManager

logger = logging.getLogger("stronghold.agents.importer")


class GitAgentImporter:
    """Import agent definitions from GitAgent directory format.

    Reads agent.yaml + SOUL.md (+ optional RULES.md) from a directory,
    builds an AgentIdentity, stores prompts via the prompt manager, and
    recursively imports sub-agents from an agents/ subdirectory.

    Idempotent: re-importing the same agent updates the existing entry.
    """

    def __init__(self, prompt_manager: InMemoryPromptManager) -> None:
        self._prompt_manager = prompt_manager
        # Track all imported agents by name for idempotent updates and sub-agent access
        self.imported: dict[str, AgentIdentity] = {}

    async def import_agent(
        self,
        path: Path,
        *,
        org_id: str,
        trust_tier: str = "t2",
    ) -> AgentIdentity:
        """Import a single agent from a directory.

        Args:
            path: Directory containing agent.yaml and SOUL.md.
            org_id: Organisation ID to assign.
            trust_tier: Trust tier override (manifest value is ignored for security).

        Returns:
            The constructed AgentIdentity.

        Raises:
            FileNotFoundError: If the directory, agent.yaml, or SOUL.md is missing.
            ValueError: If agent.yaml is malformed or missing the 'name' field.
        """
        if not path.exists():
            msg = f"Agent directory not found: {path}"
            raise FileNotFoundError(msg)

        # ── Validate required files ───────────────────────────────────
        yaml_path = path / "agent.yaml"
        if not yaml_path.exists():
            msg = f"Required file agent.yaml not found in {path}"
            raise FileNotFoundError(msg)

        soul_path = path / "SOUL.md"
        if not soul_path.exists():
            msg = f"Required file SOUL.md not found in {path}"
            raise FileNotFoundError(msg)

        # ── Parse manifest ────────────────────────────────────────────
        raw = yaml_path.read_text(encoding="utf-8")
        manifest = yaml.safe_load(raw)
        if not isinstance(manifest, dict):
            msg = "agent.yaml must be a YAML mapping"
            raise ValueError(msg)

        name = manifest.get("name", "")
        if not name:
            msg = "agent.yaml missing required 'name' field"
            raise ValueError(msg)

        # ── Read content files ────────────────────────────────────────
        soul_content = soul_path.read_text(encoding="utf-8")

        rules_path = path / "RULES.md"
        rules_content = ""
        if rules_path.exists():
            rules_content = rules_path.read_text(encoding="utf-8")

        # ── Build AgentIdentity ───────────────────────────────────────
        reasoning: dict[str, Any] = manifest.get("reasoning", {})
        identity = AgentIdentity(
            name=name,
            version=manifest.get("version", "1.0.0"),
            description=manifest.get("description", ""),
            soul_prompt_name=f"agent.{name}.soul",
            model=manifest.get("model", "auto"),
            model_fallbacks=tuple(manifest.get("model_fallbacks", ())),
            model_constraints=manifest.get("model_constraints", {}),
            tools=tuple(manifest.get("tools", ())),
            trust_tier=trust_tier,  # SECURITY: always from caller, never from manifest
            max_tool_rounds=reasoning.get("max_rounds", 3),
            reasoning_strategy=reasoning.get("strategy", "direct"),
            memory_config=manifest.get("memory", {}),
            org_id=org_id,
        )

        # ── Store prompts ─────────────────────────────────────────────
        await self._prompt_manager.upsert(
            f"agent.{name}.soul",
            soul_content,
            label="production",
        )

        if rules_content:
            await self._prompt_manager.upsert(
                f"agent.{name}.rules",
                rules_content,
                label="production",
            )

        # ── Register import ───────────────────────────────────────────
        self.imported[name] = identity
        logger.info(
            "Imported agent '%s' (org=%s, tier=%s)",
            name,
            org_id,
            trust_tier,
        )

        # ── Recurse into sub-agents ───────────────────────────────────
        agents_dir = path / "agents"
        if agents_dir.is_dir():
            for child in sorted(agents_dir.iterdir()):
                if child.is_dir() and (child / "agent.yaml").exists():
                    await self.import_agent(
                        child,
                        org_id=org_id,
                        trust_tier=trust_tier,
                    )

        return identity
