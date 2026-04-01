"""Tests for scripts/sync_prompts.py — GitHub-to-Stronghold prompt sync.

Tests use real file I/O (tmp_path) and respx for HTTP mocking.
No unittest.mock usage per project rules.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import httpx
import respx

from scripts.sync_prompts import (
    derive_name,
    discover_prompts,
    parse_prompt,
    sync_prompts,
)

# ── discover_prompts ─────────────────────────────────────────────────


class TestDiscoverPrompts:
    """discover_prompts finds files matching glob patterns."""

    def test_finds_soul_md(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "artificer"
        agent_dir.mkdir(parents=True)
        soul = agent_dir / "SOUL.md"
        soul.write_text("You are the Artificer.")

        found = discover_prompts(tmp_path, ["agents/*/SOUL.md"])
        assert len(found) == 1
        assert found[0] == soul

    def test_finds_rules_md(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "davinci"
        agent_dir.mkdir(parents=True)
        rules = agent_dir / "RULES.md"
        rules.write_text("Rule 1: Be creative.")

        found = discover_prompts(tmp_path, ["agents/*/RULES.md"])
        assert len(found) == 1
        assert found[0] == rules

    def test_finds_multiple_patterns(self, tmp_path: Path) -> None:
        art_dir = tmp_path / "agents" / "artificer"
        art_dir.mkdir(parents=True)
        (art_dir / "SOUL.md").write_text("soul content")

        dav_dir = tmp_path / "agents" / "davinci"
        dav_dir.mkdir(parents=True)
        (dav_dir / "RULES.md").write_text("rules content")

        found = discover_prompts(
            tmp_path,
            ["agents/*/SOUL.md", "agents/*/RULES.md"],
        )
        assert len(found) == 2

    def test_empty_when_no_match(self, tmp_path: Path) -> None:
        found = discover_prompts(tmp_path, ["agents/*/SOUL.md"])
        assert found == []

    def test_finds_nested_skill_files(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "agents" / "davinci" / "tools"
        skill_dir.mkdir(parents=True)
        (skill_dir / "canvas.md").write_text("canvas tool")

        found = discover_prompts(tmp_path, ["agents/*/tools/*.md"])
        assert len(found) == 1


# ── parse_prompt ─────────────────────────────────────────────────────


class TestParsePrompt:
    """parse_prompt extracts YAML frontmatter + markdown body."""

    def test_with_frontmatter(self) -> None:
        content = textwrap.dedent("""\
            ---
            version: 2
            tags: [code, tdd]
            ---

            You are the Artificer.
        """)
        meta, body = parse_prompt(content)
        assert meta == {"version": 2, "tags": ["code", "tdd"]}
        assert "You are the Artificer." in body

    def test_without_frontmatter(self) -> None:
        content = "You are the Ranger, a search specialist."
        meta, body = parse_prompt(content)
        assert meta == {}
        assert body == content

    def test_empty_frontmatter(self) -> None:
        content = "---\n---\n\nBody text here."
        meta, body = parse_prompt(content)
        assert meta == {}
        assert "Body text here." in body

    def test_body_stripped(self) -> None:
        content = "---\nkey: value\n---\n\n  Body with leading space.  \n\n"
        meta, body = parse_prompt(content)
        assert meta == {"key": "value"}
        assert body == "Body with leading space."


# ── derive_name ──────────────────────────────────────────────────────


class TestDeriveName:
    """derive_name converts file path to prompt name."""

    def test_soul_md(self) -> None:
        assert derive_name(Path("agents/artificer/SOUL.md")) == "agent.artificer.soul"

    def test_rules_md(self) -> None:
        assert derive_name(Path("agents/davinci/RULES.md")) == "agent.davinci.rules"

    def test_nested_skill(self) -> None:
        p = Path("agents/davinci/tools/canvas.md")
        assert derive_name(p) == "agent.davinci.tools.canvas"

    def test_sub_agent(self) -> None:
        p = Path("agents/artificer/agents/artificer-coder/SOUL.md")
        assert derive_name(p) == "agent.artificer.agents.artificer-coder.soul"

    def test_lowercased(self) -> None:
        assert derive_name(Path("agents/Artificer/SOUL.md")) == "agent.artificer.soul"

    def test_hyphens_preserved(self) -> None:
        p = Path("agents/warden-at-arms/SOUL.md")
        assert derive_name(p) == "agent.warden-at-arms.soul"


# ── sync_prompts (HTTP) ─────────────────────────────────────────────


class TestSyncPrompts:
    """sync_prompts sends prompts to the Stronghold API."""

    @respx.mock
    async def test_successful_upsert(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "ranger"
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("You are the Ranger.")

        base_url = "http://stronghold.test:8100"
        put_route = respx.put(f"{base_url}/api/prompts/agent.ranger.soul").mock(
            return_value=httpx.Response(200, json={"version": 1})
        )
        promote_route = respx.post(f"{base_url}/api/prompts/agent.ranger.soul/promote").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        result = await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url=base_url,
            api_key="sk-test-key",
            label="production",
        )

        assert result.synced == 1
        assert result.failed == 0
        assert put_route.called
        assert promote_route.called

    @respx.mock
    async def test_api_unreachable_graceful(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "ranger"
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("You are the Ranger.")

        base_url = "http://stronghold.test:8100"
        respx.put(f"{base_url}/api/prompts/agent.ranger.soul").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url=base_url,
            api_key="sk-test-key",
            label="production",
        )

        assert result.synced == 0
        assert result.failed == 1
        # Should not raise — graceful failure

    @respx.mock
    async def test_label_applied_after_upsert(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "scribe"
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("You are the Scribe.")

        base_url = "http://stronghold.test:8100"
        respx.put(f"{base_url}/api/prompts/agent.scribe.soul").mock(
            return_value=httpx.Response(200, json={"version": 3})
        )
        promote_route = respx.post(f"{base_url}/api/prompts/agent.scribe.soul/promote").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        result = await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url=base_url,
            api_key="sk-test-key",
            label="staging",
        )

        assert result.synced == 1
        assert promote_route.called
        # Verify the label was sent in the promote request body
        req = promote_route.calls[0].request
        assert b"staging" in req.content

    @respx.mock
    async def test_summary_report_counts(self, tmp_path: Path) -> None:
        # Create 3 agents: 2 succeed, 1 fails
        for name in ("ranger", "scribe", "arbiter"):
            d = tmp_path / "agents" / name
            d.mkdir(parents=True)
            (d / "SOUL.md").write_text(f"You are the {name}.")

        base_url = "http://stronghold.test:8100"
        respx.put(f"{base_url}/api/prompts/agent.ranger.soul").mock(
            return_value=httpx.Response(200, json={"version": 1})
        )
        respx.post(f"{base_url}/api/prompts/agent.ranger.soul/promote").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        respx.put(f"{base_url}/api/prompts/agent.scribe.soul").mock(
            return_value=httpx.Response(200, json={"version": 1})
        )
        respx.post(f"{base_url}/api/prompts/agent.scribe.soul/promote").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        respx.put(f"{base_url}/api/prompts/agent.arbiter.soul").mock(
            return_value=httpx.Response(500, json={"error": "boom"})
        )

        result = await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url=base_url,
            api_key="sk-test-key",
            label="production",
        )

        assert result.synced == 2
        assert result.failed == 1

    @respx.mock
    async def test_api_key_sent_in_header(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "ranger"
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("You are the Ranger.")

        base_url = "http://stronghold.test:8100"
        put_route = respx.put(f"{base_url}/api/prompts/agent.ranger.soul").mock(
            return_value=httpx.Response(200, json={"version": 1})
        )
        respx.post(f"{base_url}/api/prompts/agent.ranger.soul/promote").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url=base_url,
            api_key="sk-test-key",
            label="production",
        )

        req = put_route.calls[0].request
        assert req.headers["authorization"] == "Bearer sk-test-key"

    @respx.mock
    async def test_frontmatter_sent_as_config(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "ranger"
        agent_dir.mkdir(parents=True)
        content = "---\nversion: 2\ntags: [search]\n---\n\nYou are the Ranger."
        (agent_dir / "SOUL.md").write_text(content)

        base_url = "http://stronghold.test:8100"
        put_route = respx.put(f"{base_url}/api/prompts/agent.ranger.soul").mock(
            return_value=httpx.Response(200, json={"version": 2})
        )
        respx.post(f"{base_url}/api/prompts/agent.ranger.soul/promote").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )

        await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url=base_url,
            api_key="sk-test-key",
            label="production",
        )

        req = put_route.calls[0].request
        import json

        body = json.loads(req.content)
        assert body["config"]["version"] == 2
        assert body["config"]["tags"] == ["search"]

    @respx.mock
    async def test_no_files_means_zero_counts(self, tmp_path: Path) -> None:
        result = await sync_prompts(
            root=tmp_path,
            patterns=["agents/*/SOUL.md"],
            base_url="http://stronghold.test:8100",
            api_key="sk-test-key",
            label="production",
        )
        assert result.synced == 0
        assert result.failed == 0
