"""User data export for GDPR Article 20 compliance.

Exports all user-scoped data across stores into a JSON archive.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("stronghold.export")


@dataclass
class ExportResult:
    """Result of a user data export."""

    user_id: str
    org_id: str
    exported_at: str = ""
    sections: dict[str, Any] = field(default_factory=dict)
    record_counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize export to JSON with schema version."""
        return json.dumps(
            {
                "user_id": self.user_id,
                "org_id": self.org_id,
                "exported_at": self.exported_at,
                "schema_version": "1.0",
                "record_counts": self.record_counts,
                "data": self.sections,
            },
            indent=2,
            default=str,
        )


class UserDataExporter:
    """Export all user data from configured stores."""

    def __init__(
        self,
        session_store: Any = None,
        learning_store: Any = None,
        episodic_store: Any = None,
    ) -> None:
        self._sessions = session_store
        self._learnings = learning_store
        self._episodic = episodic_store

    async def export_user(self, *, user_id: str, org_id: str) -> ExportResult:
        """Export all data for a user across all configured stores."""
        result = ExportResult(
            user_id=user_id,
            org_id=org_id,
            exported_at=datetime.now(UTC).isoformat(),
        )

        # Sessions/conversations
        if self._sessions is not None:
            sessions = await self._export_sessions(user_id=user_id, org_id=org_id)
            result.sections["conversations"] = sessions
            result.record_counts["conversations"] = len(sessions)

        # Learnings
        if self._learnings is not None:
            learnings = await self._export_learnings(org_id=org_id)
            result.sections["learnings"] = learnings
            result.record_counts["learnings"] = len(learnings)

        # Episodic memories
        if self._episodic is not None:
            memories = await self._export_episodic(user_id=user_id, org_id=org_id)
            result.sections["memories"] = memories
            result.record_counts["memories"] = len(memories)

        return result

    async def _export_sessions(self, *, user_id: str, org_id: str) -> list[dict[str, Any]]:
        """Export session/conversation data.

        Session IDs are formatted as "org_id/team_id/user_id:session_name".
        We iterate all stored sessions and filter by org_id prefix + user_id.
        """
        results: list[dict[str, Any]] = []
        # InMemorySessionStore exposes _sessions dict
        sessions_dict: dict[str, Any] = getattr(self._sessions, "_sessions", {})
        for session_id in list(sessions_dict.keys()):
            # Session IDs: "org_id/team_id/user_id:session_name"
            if not session_id.startswith(f"{org_id}/"):
                continue
            # Check user_id appears in the session_id
            if f"/{user_id}:" not in session_id:
                continue
            messages = await self._sessions.get_history(session_id, ttl_seconds=10**9)
            results.append(
                {
                    "session_id": session_id,
                    "messages": messages,
                    "message_count": len(messages),
                }
            )
        return results

    async def _export_learnings(self, *, org_id: str) -> list[dict[str, Any]]:
        """Export learnings data for the org."""
        all_learnings = await self._learnings.list_all(org_id=org_id)
        return [
            {
                "id": lr.id,
                "category": lr.category,
                "trigger_keys": lr.trigger_keys,
                "learning": lr.learning,
                "tool_name": lr.tool_name,
                "agent_id": lr.agent_id,
                "scope": str(lr.scope),
                "hit_count": lr.hit_count,
                "status": lr.status,
                "org_id": lr.org_id,
            }
            for lr in all_learnings
        ]

    async def _export_episodic(self, *, user_id: str, org_id: str) -> list[dict[str, Any]]:
        """Export episodic memories for a user within an org."""
        results: list[dict[str, Any]] = []
        # InMemoryEpisodicStore exposes _memories list
        memories: list[Any] = getattr(self._episodic, "_memories", [])
        for mem in memories:
            if mem.deleted:
                continue
            if mem.org_id != org_id:
                continue
            if mem.user_id != user_id:
                continue
            results.append(
                {
                    "memory_id": mem.memory_id,
                    "tier": str(mem.tier),
                    "content": mem.content,
                    "weight": mem.weight,
                    "scope": str(mem.scope),
                    "source": mem.source,
                    "created_at": str(mem.created_at),
                }
            )
        return results
