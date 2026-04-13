"""Prompt manager protocol — PostgreSQL-backed prompt library."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PromptManager(Protocol):
    """Fetches and manages versioned prompts."""

    async def get(self, name: str, *, label: str = "production") -> str:
        """Fetch a prompt by name and label."""
        ...

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata."""
        ...

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Create a new version of a prompt."""
        ...

    async def list_prompts(self) -> list[dict[str, Any]]:
        """List all prompts with metadata."""
        ...

    async def get_version_history(self, name: str) -> dict[str, Any] | None:
        """Get full version history for a prompt."""
        ...

    async def get_label_version(self, name: str, label: str) -> int | None:
        """Get the version number that a label points to."""
        ...

    async def set_label(self, name: str, label: str, version: int) -> None:
        """Set a label to point at a specific version."""
        ...

    async def get_latest_version(self, name: str) -> int:
        """Get the latest version number for a prompt."""
        ...

    async def get_version_content(
        self,
        name: str,
        version: int,
    ) -> tuple[str, dict[str, Any]] | None:
        """Get content and config for a specific version."""
        ...

    async def has_version(self, name: str, version: int) -> bool:
        """Check whether a specific version exists."""
        ...

    def scoped_name(self, name: str, org_id: str = "") -> str:
        """Build org-scoped prompt key."""
        ...
