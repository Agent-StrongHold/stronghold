#!/usr/bin/env python3
"""Sync prompt files from git repo to Stronghold prompt API.

Discovers prompt markdown files (SOUL.md, RULES.md, skill docs) in the repo,
parses YAML frontmatter + body, and pushes each to Stronghold's prompt API.

Usage:
    STRONGHOLD_URL=http://localhost:8100 STRONGHOLD_API_KEY=sk-... python scripts/sync_prompts.py

Environment:
    STRONGHOLD_URL: Stronghold API base URL
    STRONGHOLD_API_KEY: API key for authentication
    SYNC_LABEL: Label to apply (default: "production")
    PROMPT_PATHS: Comma-separated glob patterns (default: "agents/*/SOUL.md,agents/*/RULES.md")
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)

_DEFAULT_PATTERNS = [
    "agents/*/SOUL.md",
    "agents/*/RULES.md",
    "agents/*/skills/*.md",
    "agents/*/tools/*.md",
]


@dataclass
class SyncResult:
    """Summary of a sync run."""

    synced: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def discover_prompts(root: Path, patterns: list[str]) -> list[Path]:
    """Find prompt files matching glob patterns under root.

    Args:
        root: Repository root directory.
        patterns: List of glob patterns relative to root.

    Returns:
        Sorted list of matching file paths.
    """
    found: list[Path] = []
    for pattern in patterns:
        found.extend(root.glob(pattern))
    return sorted(set(found))


def parse_prompt(content: str) -> tuple[dict[str, object], str]:
    """Extract YAML frontmatter and markdown body from a prompt file.

    Args:
        content: Raw file content.

    Returns:
        Tuple of (metadata dict, body string). Metadata is empty dict if
        no frontmatter is present.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    raw_yaml = match.group(1).strip()
    if not raw_yaml:
        return {}, match.group(2).strip()

    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        return {}, match.group(2).strip()

    if not isinstance(meta, dict):
        return {}, match.group(2).strip()

    return meta, match.group(2).strip()


def derive_name(path: Path) -> str:
    """Convert a prompt file path to a dotted prompt name.

    ``agents/artificer/SOUL.md`` becomes ``agent.artificer.soul``.
    The leading ``agents`` directory is singularized to ``agent``.

    Args:
        path: Path relative to repo root (e.g. ``Path("agents/artificer/SOUL.md")``).

    Returns:
        Dotted, lowercase prompt name.
    """
    parts = list(path.parts)

    # Singularize leading "agents" directory
    if parts and parts[0].lower() == "agents":
        parts[0] = "agent"

    # Strip .md extension from the last part
    if parts:
        parts[-1] = Path(parts[-1]).stem

    return ".".join(p.lower() for p in parts)


async def sync_prompts(
    *,
    root: Path,
    patterns: list[str],
    base_url: str,
    api_key: str,
    label: str,
) -> SyncResult:
    """Discover, parse, and sync prompts to the Stronghold API.

    Args:
        root: Repository root directory.
        patterns: Glob patterns for prompt files.
        base_url: Stronghold API base URL.
        api_key: API key for authentication.
        label: Label to apply after upsert (e.g. "production", "staging").

    Returns:
        SyncResult with counts of synced, failed, and error messages.
    """
    result = SyncResult()
    files = discover_prompts(root, patterns)

    if not files:
        return result

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
        for filepath in files:
            rel = filepath.relative_to(root)
            name = derive_name(rel)
            content = filepath.read_text(encoding="utf-8")
            meta, body = parse_prompt(content)

            # PUT /api/prompts/{name} — upsert
            payload = {"content": body, "config": meta}
            try:
                resp = await client.put(
                    f"{base_url}/api/prompts/{name}",
                    content=json.dumps(payload),
                )
                if resp.status_code >= 400:
                    result.failed += 1
                    result.errors.append(f"{name}: HTTP {resp.status_code}")
                    continue
            except httpx.HTTPError as exc:
                result.failed += 1
                result.errors.append(f"{name}: {exc}")
                continue

            # POST /api/prompts/{name}/promote — apply label
            with contextlib.suppress(httpx.HTTPError):
                await client.post(
                    f"{base_url}/api/prompts/{name}/promote",
                    content=json.dumps({"label": label}),
                )

            result.synced += 1

    return result


async def _main() -> None:
    """Entry point when run as a script."""
    base_url = os.environ.get("STRONGHOLD_URL", "")
    api_key = os.environ.get("STRONGHOLD_API_KEY", "")
    label = os.environ.get("SYNC_LABEL", "production")
    patterns_raw = os.environ.get("PROMPT_PATHS", "")

    if not base_url:
        print("ERROR: STRONGHOLD_URL not set", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print("ERROR: STRONGHOLD_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    patterns = (
        [p.strip() for p in patterns_raw.split(",") if p.strip()]
        if patterns_raw
        else _DEFAULT_PATTERNS
    )

    root = Path.cwd()
    result = await sync_prompts(
        root=root,
        patterns=patterns,
        base_url=base_url,
        api_key=api_key,
        label=label,
    )

    print(f"Synced: {result.synced}  Failed: {result.failed}")
    for err in result.errors:
        print(f"  ERROR: {err}", file=sys.stderr)

    if result.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
