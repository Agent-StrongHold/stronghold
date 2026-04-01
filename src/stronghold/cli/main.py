"""Stronghold CLI entry point.

Subcommands:
    agent list                  List all registered agents
    agent import <path>         Import an agent from a GitAgent zip
    agent export <name> <out>   Export an agent to a GitAgent zip
    status                      Show system status (agents, intents, quota)
    status models               List available models
    status quota                Show quota usage per provider

Environment:
    STRONGHOLD_URL      Base URL (default: http://localhost:8100)
    STRONGHOLD_API_KEY  API key for authentication
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import IO, Any

import httpx


def get_client_config() -> dict[str, str]:
    """Read connection config from environment variables."""
    return {
        "base_url": os.environ.get("STRONGHOLD_URL", "http://localhost:8100"),
        "api_key": os.environ.get("STRONGHOLD_API_KEY", ""),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="stronghold",
        description="Stronghold CLI — Secure Agent Governance Platform",
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format (default: table)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── agent ───────────────────────────────────────────────────────
    agent_parser = subparsers.add_parser("agent", help="Agent management")
    agent_sub = agent_parser.add_subparsers(dest="agent_action", required=True)

    # agent list
    list_parser = agent_sub.add_parser("list", help="List all agents")
    list_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format",
    )

    # agent import <path>
    import_parser = agent_sub.add_parser("import", help="Import agent from zip")
    import_parser.add_argument("path", help="Path to GitAgent zip file")
    import_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format",
    )

    # agent export <name> <output>
    export_parser = agent_sub.add_parser("export", help="Export agent to zip")
    export_parser.add_argument("name", help="Agent name to export")
    export_parser.add_argument("output", help="Output path for zip file")
    export_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format",
    )

    # ── status ──────────────────────────────────────────────────────
    status_parser = subparsers.add_parser("status", help="System status")
    status_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format",
    )
    status_sub = status_parser.add_subparsers(dest="status_action")

    # status models
    models_parser = status_sub.add_parser("models", help="List available models")
    models_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format",
    )

    # status quota
    quota_parser = status_sub.add_parser("quota", help="Show quota usage")
    quota_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format",
    )

    return parser


def format_output(data: Any, *, fmt: str = "table") -> str:
    """Format data as JSON or a human-readable table.

    Handles both list-of-dicts (e.g. agent list) and single dicts (e.g. status).
    """
    if fmt == "json":
        return json.dumps(data, indent=2, default=str)

    # Table format
    if isinstance(data, list):
        if not data:
            return "No results."
        if isinstance(data[0], dict):
            keys = list(data[0].keys())
            widths = {k: max(len(k), *(len(str(row.get(k, ""))) for row in data)) for k in keys}
            header = "  ".join(k.ljust(widths[k]) for k in keys)
            sep = "  ".join("-" * widths[k] for k in keys)
            rows = ["  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys) for row in data]
            return "\n".join([header, sep, *rows])
        return "\n".join(str(item) for item in data)

    if isinstance(data, dict):
        max_key = max(len(str(k)) for k in data) if data else 0
        lines = [f"{str(k).ljust(max_key)}  {v}" for k, v in data.items()]
        return "\n".join(lines)

    return str(data)


def _make_headers(api_key: str) -> dict[str, str]:
    """Build HTTP headers for Stronghold API requests."""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def _agent_list(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    fmt: str,
    output: IO[str],
) -> int:
    """List all agents."""
    resp = await client.get("/v1/stronghold/agents", headers=headers)
    if resp.status_code != 200:  # noqa: PLR2004
        output.write(f"Error {resp.status_code}: {resp.text}\n")
        return 1
    data = resp.json()
    output.write(format_output(data, fmt=fmt) + "\n")
    return 0


async def _agent_import(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    path: str,
    fmt: str,
    output: IO[str],
) -> int:
    """Import an agent from a zip file."""
    zip_path = Path(path)
    if not zip_path.exists():
        output.write(f"Error: file not found: {path}\n")
        return 1
    zip_data = zip_path.read_bytes()
    resp = await client.post(
        "/v1/stronghold/agents/import",
        content=zip_data,
        headers={**headers, "content-type": "application/octet-stream"},
    )
    if resp.status_code not in (200, 201):
        output.write(f"Error {resp.status_code}: {resp.text}\n")
        return 1
    data = resp.json()
    output.write(format_output(data, fmt=fmt) + "\n")
    return 0


async def _agent_export(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    name: str,
    output_path: str,
    output: IO[str],
) -> int:
    """Export an agent to a zip file."""
    resp = await client.get(f"/v1/stronghold/agents/{name}/export", headers=headers)
    if resp.status_code != 200:  # noqa: PLR2004
        output.write(f"Error {resp.status_code}: {resp.text}\n")
        return 1
    Path(output_path).write_bytes(resp.content)
    output.write(f"Exported '{name}' to {output_path}\n")
    return 0


async def _status(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    fmt: str,
    output: IO[str],
) -> int:
    """Show system status."""
    resp = await client.get("/v1/stronghold/status", headers=headers)
    if resp.status_code != 200:  # noqa: PLR2004
        output.write(f"Error {resp.status_code}: {resp.text}\n")
        return 1
    data = resp.json()
    output.write(format_output(data, fmt=fmt) + "\n")
    return 0


async def _status_models(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    fmt: str,
    output: IO[str],
) -> int:
    """List available models."""
    resp = await client.get("/v1/models", headers=headers)
    if resp.status_code != 200:  # noqa: PLR2004
        output.write(f"Error {resp.status_code}: {resp.text}\n")
        return 1
    data = resp.json()
    output.write(format_output(data, fmt=fmt) + "\n")
    return 0


async def _status_quota(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    fmt: str,
    output: IO[str],
) -> int:
    """Show quota usage."""
    resp = await client.get("/v1/stronghold/status", headers=headers)
    if resp.status_code != 200:  # noqa: PLR2004
        output.write(f"Error {resp.status_code}: {resp.text}\n")
        return 1
    data = resp.json()
    quota = data.get("quota_usage", {})
    output.write(format_output(quota, fmt=fmt) + "\n")
    return 0


async def run(
    argv: list[str] | None = None,
    *,
    env_url: str | None = None,
    env_key: str | None = None,
    output: IO[str] | None = None,
) -> int:
    """Run the CLI with the given arguments.

    Parameters allow injection for testing: env_url/env_key override environment
    variables, output overrides sys.stdout.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    out = output or sys.stdout
    fmt: str = args.format

    # Resolve config
    if env_url is None or env_key is None:
        cfg = get_client_config()
        base_url = env_url if env_url is not None else cfg["base_url"]
        api_key = env_key if env_key is not None else cfg["api_key"]
    else:
        base_url = env_url
        api_key = env_key

    headers = _make_headers(api_key)

    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            if args.command == "agent":
                if args.agent_action == "list":
                    return await _agent_list(client, headers, fmt, out)
                if args.agent_action == "import":
                    return await _agent_import(client, headers, args.path, fmt, out)
                if args.agent_action == "export":
                    return await _agent_export(client, headers, args.name, args.output, out)
            elif args.command == "status":
                action = getattr(args, "status_action", None)
                if action == "models":
                    return await _status_models(client, headers, fmt, out)
                if action == "quota":
                    return await _status_quota(client, headers, fmt, out)
                return await _status(client, headers, fmt, out)
    except httpx.ConnectError as exc:
        out.write(f"Error: could not connect to {base_url} ({exc})\n")
        return 1
    except httpx.HTTPError as exc:
        out.write(f"Error: HTTP request failed ({exc})\n")
        return 1

    return 0


def main() -> None:
    """Console script entry point."""
    code = asyncio.run(run())
    sys.exit(code)


if __name__ == "__main__":
    main()
