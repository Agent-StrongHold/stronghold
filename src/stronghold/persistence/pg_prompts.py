"""PostgreSQL prompt manager."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg


class PgPromptManager:
    """PostgreSQL-backed versioned prompt store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, name: str, *, label: str = "production") -> str:
        """Fetch prompt content by name and label."""
        content, _ = await self.get_with_config(name, label=label)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content, config FROM prompts WHERE name = $1 AND label = $2",
                name,
                label,
            )
            if row:
                config = _parse_config(row["config"])
                return str(row["content"]), config

            # Fallback to latest version
            row = await conn.fetchrow(
                "SELECT content, config FROM prompts WHERE name = $1 ORDER BY version DESC LIMIT 1",
                name,
            )
            if row:
                config = _parse_config(row["config"])
                return str(row["content"]), config
        return "", {}

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Create a new version of a prompt."""
        config_json = json.dumps(config or {})
        async with self._pool.acquire() as conn:
            # Get next version
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM prompts WHERE name = $1",
                name,
            )
            next_ver: int = row["next_ver"] if row else 1

            # Remove old label assignment if exists
            if label:
                await conn.execute(
                    "UPDATE prompts SET label = NULL WHERE name = $1 AND label = $2",
                    name,
                    label,
                )

            # Also update 'latest' label
            await conn.execute(
                "UPDATE prompts SET label = NULL WHERE name = $1 AND label = 'latest'",
                name,
            )

            # Insert new version
            effective_label = label or "latest"
            await conn.execute(
                """INSERT INTO prompts (name, version, label, content, config)
                   VALUES ($1, $2, $3, $4, $5::jsonb)""",
                name,
                next_ver,
                effective_label,
                content,
                config_json,
            )

            # If first version, also set production
            if next_ver == 1 and effective_label != "production":
                await conn.execute(
                    """INSERT INTO prompts (name, version, label, content, config)
                       VALUES ($1, $2, 'production', $3, $4::jsonb)
                       ON CONFLICT (name, label)
                       DO UPDATE SET version = $2, content = $3, config = $4::jsonb""",
                    name,
                    next_ver,
                    content,
                    config_json,
                )


def _parse_config(raw: Any) -> dict[str, Any]:
    """Parse config from DB row (may be str, dict, or None)."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        result: dict[str, Any] = json.loads(raw)
        return result
    if isinstance(raw, dict):
        return dict(raw)
    return {}

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List all prompts with their current labels and version counts."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT name,
                          COUNT(DISTINCT version) AS ver_count,
                          MAX(version) AS latest_version
                   FROM prompts
                   GROUP BY name
                   ORDER BY name"""
            )
        result: list[dict[str, Any]] = []
        for row in rows:
            name = str(row["name"])
            latest = int(row["latest_version"])
            content, config = await self.get_with_config(name, label="latest")
            labels_data = await self._get_labels(name)
            result.append(
                {
                    "name": name,
                    "versions": int(row["ver_count"]),
                    "labels": labels_data,
                    "latest_version": latest,
                    "content_preview": (content[:100] + "..." if len(content) > 100 else content),
                }
            )
        return result

    async def _get_labels(self, name: str) -> dict[str, int]:
        """Get label->version mapping for a prompt."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT label, version FROM prompts WHERE name = $1 AND label IS NOT NULL",
                name,
            )
        return {str(r["label"]): int(r["version"]) for r in rows}

    async def get_version_history(self, name: str) -> dict[str, Any] | None:
        """Get full version history for a prompt, or None if not found."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT version, label, content, config
                   FROM prompts WHERE name = $1 ORDER BY version""",
                name,
            )
        if not rows:
            return None
        labels_data = await self._get_labels(name)
        version_labels: dict[int, list[str]] = {}
        for lbl, ver in labels_data.items():
            version_labels.setdefault(ver, []).append(lbl)
        version_list: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in rows:
            ver = int(row["version"])
            if ver in seen:
                continue
            seen.add(ver)
            content = str(row["content"])
            config = _parse_config(row["config"])
            version_list.append(
                {
                    "version": ver,
                    "labels": version_labels.get(ver, []),
                    "content_preview": (content[:100] + "..." if len(content) > 100 else content),
                    "config": config,
                }
            )
        return {"name": name, "versions": version_list, "labels": labels_data}

    async def get_label_version(self, name: str, label: str) -> int | None:
        """Get the version number that a label points to, or None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT version FROM prompts WHERE name = $1 AND label = $2",
                name,
                label,
            )
        return int(row["version"]) if row else None

    async def set_label(self, name: str, label: str, version: int) -> None:
        """Set a label to point at a specific version."""
        async with self._pool.acquire() as conn:
            # Get the content/config from the target version
            row = await conn.fetchrow(
                "SELECT content, config FROM prompts WHERE name = $1 AND version = $2 LIMIT 1",
                name,
                version,
            )
            if not row:
                return
            # Remove old label
            await conn.execute(
                "UPDATE prompts SET label = NULL WHERE name = $1 AND label = $2",
                name,
                label,
            )
            # Upsert with the new label
            await conn.execute(
                """INSERT INTO prompts (name, version, label, content, config)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (name, label)
                   DO UPDATE SET version = $2, content = $4, config = $5""",
                name,
                version,
                label,
                row["content"],
                row["config"],
            )

    async def get_latest_version(self, name: str) -> int:
        """Get the latest (highest) version number for a prompt."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(version), 0) AS max_ver FROM prompts WHERE name = $1",
                name,
            )
        return int(row["max_ver"]) if row else 0

    async def get_version_content(
        self,
        name: str,
        version: int,
    ) -> tuple[str, dict[str, Any]] | None:
        """Get content and config for a specific version, or None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content, config FROM prompts WHERE name = $1 AND version = $2 LIMIT 1",
                name,
                version,
            )
        if not row:
            return None
        return str(row["content"]), _parse_config(row["config"])

    async def has_version(self, name: str, version: int) -> bool:
        """Check whether a specific version exists for a prompt."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM prompts WHERE name = $1 AND version = $2 LIMIT 1",
                name,
                version,
            )
        return row is not None

    @staticmethod
    def scoped_name(name: str, org_id: str = "") -> str:
        """Build org-scoped prompt key. System/agent prompts use raw name."""
        is_shared = name.startswith("agent.") or name.startswith("system.")
        if not org_id or org_id == "__system__" or is_shared:
            return name
        return f"{org_id}:{name}"
