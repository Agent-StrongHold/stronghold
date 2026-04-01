"""Tests for the Stronghold CLI.

Covers argument parsing, output formatting, env var config, and HTTP interactions
using respx to mock external calls.
"""

from __future__ import annotations

import json
import os
from io import StringIO
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from stronghold.cli.main import build_parser, format_output, run

# ── Argument Parsing ────────────────────────────────────────────────


class TestBuildParser:
    """Verify argparse subcommands and options are wired correctly."""

    def test_agent_list_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "list"])
        assert args.command == "agent"
        assert args.agent_action == "list"

    def test_agent_list_with_json_format(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "list", "--format", "json"])
        assert args.format == "json"

    def test_agent_list_with_table_format(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "list", "--format", "table"])
        assert args.format == "table"

    def test_agent_import_requires_path(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "import", "/tmp/agent.zip"])
        assert args.agent_action == "import"
        assert args.path == "/tmp/agent.zip"

    def test_agent_import_missing_path_exits(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["agent", "import"])

    def test_agent_export_requires_name_and_output(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "export", "ranger", "/tmp/ranger.zip"])
        assert args.agent_action == "export"
        assert args.name == "ranger"
        assert args.output == "/tmp/ranger.zip"

    def test_agent_export_missing_output_exits(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["agent", "export", "ranger"])

    def test_status_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_status_models_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status", "models"])
        assert args.status_action == "models"

    def test_status_quota_parses(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status", "quota"])
        assert args.status_action == "quota"

    def test_default_format_is_table(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["agent", "list"])
        assert args.format == "table"

    def test_no_command_prints_help(self) -> None:
        """No subcommand should exit with error."""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


# ── Output Formatting ───────────────────────────────────────────────


class TestFormatOutput:
    """Verify JSON and table rendering."""

    def test_json_format_agents_list(self) -> None:
        data: list[dict[str, Any]] = [
            {"name": "arbiter", "description": "Triage agent", "trust_tier": "t0"},
            {"name": "ranger", "description": "Search agent", "trust_tier": "t0"},
        ]
        result = format_output(data, fmt="json")
        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "arbiter"

    def test_table_format_agents_list(self) -> None:
        data: list[dict[str, Any]] = [
            {"name": "arbiter", "description": "Triage agent", "trust_tier": "t0"},
        ]
        result = format_output(data, fmt="table")
        assert "arbiter" in result
        assert "Triage agent" in result
        # Table should have header row
        assert "name" in result.lower()

    def test_json_format_single_dict(self) -> None:
        data: dict[str, Any] = {"agents": 5, "agent_names": ["a", "b"]}
        result = format_output(data, fmt="json")
        parsed = json.loads(result)
        assert parsed["agents"] == 5

    def test_table_format_single_dict(self) -> None:
        data: dict[str, Any] = {"agents": 5, "status": "ok"}
        result = format_output(data, fmt="table")
        assert "agents" in result
        assert "5" in result

    def test_table_format_empty_list(self) -> None:
        result = format_output([], fmt="table")
        assert "No results" in result


# ── Environment Variable Configuration ──────────────────────────────


class TestEnvConfig:
    """Verify STRONGHOLD_URL and STRONGHOLD_API_KEY are read correctly."""

    def test_default_url(self) -> None:
        env: dict[str, str] = {}
        with patch.dict(os.environ, env, clear=True):
            from stronghold.cli.main import get_client_config

            cfg = get_client_config()
            assert cfg["base_url"] == "http://localhost:8100"

    def test_custom_url_from_env(self) -> None:
        env = {"STRONGHOLD_URL": "https://stronghold.example.com"}
        with patch.dict(os.environ, env, clear=True):
            from stronghold.cli.main import get_client_config

            cfg = get_client_config()
            assert cfg["base_url"] == "https://stronghold.example.com"

    def test_api_key_from_env(self) -> None:
        env = {"STRONGHOLD_API_KEY": "sk-test-12345"}
        with patch.dict(os.environ, env, clear=True):
            from stronghold.cli.main import get_client_config

            cfg = get_client_config()
            assert cfg["api_key"] == "sk-test-12345"


# ── HTTP Integration (respx) ───────────────────────────────────────


class TestCLIAgentCommands:
    """Test CLI agent subcommands with mocked HTTP."""

    @respx.mock
    async def test_agent_list_calls_api(self) -> None:
        route = respx.get("http://localhost:8100/v1/stronghold/agents").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"name": "arbiter", "description": "Triage", "trust_tier": "t0"},
                ],
            )
        )
        buf = StringIO()
        await run(
            ["agent", "list", "--format", "json"],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        assert route.called
        output = json.loads(buf.getvalue())
        assert output[0]["name"] == "arbiter"

    @respx.mock
    async def test_agent_list_table_format(self) -> None:
        respx.get("http://localhost:8100/v1/stronghold/agents").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"name": "ranger", "description": "Search agent", "trust_tier": "t0"},
                ],
            )
        )
        buf = StringIO()
        await run(
            ["agent", "list", "--format", "table"],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        text = buf.getvalue()
        assert "ranger" in text

    @respx.mock
    async def test_agent_import_sends_file(self, tmp_path: Any) -> None:
        zip_file = tmp_path / "agent.zip"
        zip_file.write_bytes(b"PK\x03\x04fake-zip-data")

        route = respx.post("http://localhost:8100/v1/stronghold/agents/import").mock(
            return_value=httpx.Response(
                201,
                json={"name": "imported_agent", "status": "imported"},
            )
        )
        buf = StringIO()
        await run(
            ["agent", "import", str(zip_file)],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        assert route.called

    @respx.mock
    async def test_agent_export_saves_file(self, tmp_path: Any) -> None:
        respx.get("http://localhost:8100/v1/stronghold/agents/ranger/export").mock(
            return_value=httpx.Response(
                200,
                content=b"PK\x03\x04fake-zip-data",
                headers={"content-type": "application/zip"},
            )
        )
        output_path = tmp_path / "ranger.zip"
        buf = StringIO()
        await run(
            ["agent", "export", "ranger", str(output_path)],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        assert output_path.exists()
        assert output_path.read_bytes() == b"PK\x03\x04fake-zip-data"


class TestCLIStatusCommands:
    """Test CLI status subcommands with mocked HTTP."""

    @respx.mock
    async def test_status_calls_api(self) -> None:
        respx.get("http://localhost:8100/v1/stronghold/status").mock(
            return_value=httpx.Response(
                200,
                json={"agents": 6, "agent_names": ["arbiter", "ranger"]},
            )
        )
        buf = StringIO()
        await run(
            ["status", "--format", "json"],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        output = json.loads(buf.getvalue())
        assert output["agents"] == 6

    @respx.mock
    async def test_status_models_calls_api(self) -> None:
        respx.get("http://localhost:8100/v1/models").mock(
            return_value=httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [
                        {"id": "gpt-4", "object": "model", "owned_by": "openai"},
                    ],
                },
            )
        )
        buf = StringIO()
        await run(
            ["status", "models", "--format", "json"],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        output = json.loads(buf.getvalue())
        assert output["data"][0]["id"] == "gpt-4"

    @respx.mock
    async def test_status_quota_calls_api(self) -> None:
        respx.get("http://localhost:8100/v1/stronghold/status").mock(
            return_value=httpx.Response(
                200,
                json={
                    "agents": 3,
                    "agent_names": ["a"],
                    "quota_usage": {"test_provider": {"used": 100, "limit": 1000}},
                },
            )
        )
        buf = StringIO()
        await run(
            ["status", "quota", "--format", "json"],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        output = json.loads(buf.getvalue())
        assert "test_provider" in output


class TestCLIErrorHandling:
    """Test error scenarios."""

    @respx.mock
    async def test_auth_failure_reports_error(self) -> None:
        respx.get("http://localhost:8100/v1/stronghold/agents").mock(
            return_value=httpx.Response(401, json={"detail": "Invalid API key"})
        )
        buf = StringIO()
        code = await run(
            ["agent", "list"],
            env_url="http://localhost:8100",
            env_key="bad-key",
            output=buf,
        )
        assert code != 0
        assert "401" in buf.getvalue() or "error" in buf.getvalue().lower()

    @respx.mock
    async def test_connection_error_reports_error(self) -> None:
        respx.get("http://localhost:8100/v1/stronghold/agents").mock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        buf = StringIO()
        code = await run(
            ["agent", "list"],
            env_url="http://localhost:8100",
            env_key="sk-test",
            output=buf,
        )
        assert code != 0
        assert "error" in buf.getvalue().lower()
