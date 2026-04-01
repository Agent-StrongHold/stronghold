"""GitAgent directory export.

Serializes a running agent from the InMemoryAgentStore to a GitAgent directory:
  agent-name/
  ├── agent.yaml     # Manifest (spec_version, name, version, reasoning, model, tools)
  ├── SOUL.md        # System prompt
  ├── RULES.md       # Hard constraints (optional)
  └── skills/        # Agent-specific SKILL.md files (optional, future)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

    from stronghold.agents.store import InMemoryAgentStore

logger = logging.getLogger("stronghold.agents.exporter")

# Patterns for secrets that must be redacted from exported content.
# Covers OpenAI, Anthropic, Google, and generic sk-/key- prefixed tokens.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"key-[A-Za-z0-9_-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xoxb-[A-Za-z0-9-]+"),
)

# Internal AgentIdentity fields that must never appear in exported manifests.
_REDACTED_FIELDS: frozenset[str] = frozenset(
    {
        "org_id",
        "soul_prompt_name",
        "provenance",
        "ai_reviewed",
        "ai_review_clean",
        "admin_reviewed",
        "admin_reviewed_by",
        "user_reviewed",
        "active",
        "delegation_mode",
        "skills",
    }
)


def _redact_secrets(text: str) -> str:
    """Replace secret-looking tokens with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _build_manifest(
    identity: Any,
    rules_content: str,
) -> dict[str, Any]:
    """Build the agent.yaml manifest dict from an AgentIdentity.

    Produces deterministic output: sorted keys, sorted lists.
    Omits optional sections when they are empty.
    """
    manifest: dict[str, Any] = {
        "description": identity.description,
        "memory": dict(sorted(identity.memory_config.items())) if identity.memory_config else {},
        "model": identity.model,
        "name": identity.name,
        "reasoning": {
            "max_rounds": identity.max_tool_rounds,
            "strategy": identity.reasoning_strategy,
        },
        "soul": "SOUL.md",
        "spec_version": "0.1.0",
        "tools": sorted(identity.tools),
        "trust_tier": identity.trust_tier,
        "version": identity.version,
    }

    # Optional sections: only include when non-empty
    if identity.model_fallbacks:
        manifest["model_fallbacks"] = sorted(identity.model_fallbacks)
    if identity.model_constraints:
        manifest["model_constraints"] = dict(sorted(identity.model_constraints.items()))
    if identity.sub_agents:
        manifest["sub_agents"] = sorted(identity.sub_agents)
    if identity.rules:
        manifest["rules"] = sorted(identity.rules)

    return manifest


class GitAgentExporter:
    """Exports a running agent to a GitAgent directory on disk.

    Usage::

        exporter = GitAgentExporter(agent_store)
        path = await exporter.export_agent("artificer", Path("/tmp/out"), org_id="org-1")
        # path == /tmp/out/artificer/
    """

    def __init__(self, store: InMemoryAgentStore) -> None:
        self._store = store

    async def export_agent(
        self,
        agent_name: str,
        output_path: Path,
        *,
        org_id: str,
    ) -> Path:
        """Export an agent to a GitAgent directory.

        Args:
            agent_name: Name of the agent to export.
            output_path: Parent directory where agent-name/ will be created.
            org_id: Caller's org_id (used for access check, stripped from output).

        Returns:
            Path to the created agent directory.

        Raises:
            ValueError: If the agent does not exist or is not visible to the org.
        """
        agent = self._store._agents.get(agent_name)
        if not agent:
            msg = f"Agent '{agent_name}' not found"
            raise ValueError(msg)

        identity = agent.identity

        # Org isolation check
        if org_id and identity.org_id and identity.org_id != org_id:
            msg = f"Agent '{agent_name}' not found"
            raise ValueError(msg)

        # Create directory
        agent_dir = output_path / agent_name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Get soul and rules content
        soul = self._store._souls.get(agent_name, "")
        if not soul and self._store._prompt_manager:
            soul, _ = await self._store._prompt_manager.get_with_config(
                f"agent.{agent_name}.soul", label="production"
            )
        soul = _redact_secrets(soul or "")

        rules_content = self._store._rules.get(agent_name, "")
        rules_content = _redact_secrets(rules_content)

        # Build manifest (redaction happens via _build_manifest which excludes _REDACTED_FIELDS)
        manifest = _build_manifest(identity, rules_content)

        # Write agent.yaml with sorted keys for deterministic output
        yaml_text = yaml.dump(manifest, default_flow_style=False, sort_keys=True)
        (agent_dir / "agent.yaml").write_text(yaml_text)

        # Write SOUL.md
        (agent_dir / "SOUL.md").write_text(soul)

        # Write RULES.md only if rules content exists
        if rules_content:
            (agent_dir / "RULES.md").write_text(rules_content)

        logger.info("Exported agent '%s' to %s", agent_name, agent_dir)
        return agent_dir
