"""Session store: conversation history for thin clients.

In-memory implementation for testing. PostgreSQL version uses asyncpg.
Session IDs are org-scoped: format is "org_id/team_id/user_id:session_name".
The store itself doesn't enforce org isolation — callers must use scoped IDs.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

from stronghold.types.session import SessionConfig

logger = logging.getLogger("stronghold.sessions.store")


def build_session_id(
    org_id: str,
    team_id: str,
    user_id: str,
    session_name: str,
) -> str:
    """Build an org-scoped session ID.

    Format: "org_id/team_id/user_id:session_name"
    This ensures sessions are namespaced by org+team+user.
    """
    return f"{org_id}/{team_id}/{user_id}:{session_name}"


def validate_session_ownership(
    session_id: str,
    org_id: str,
) -> bool:
    """Validate that a session_id belongs to the given org.

    Returns False if the session_id doesn't start with the org prefix.
    """
    if not org_id:
        return False  # Empty org_id must not bypass validation
    return session_id.startswith(f"{org_id}/")


def validate_and_build_session_id(
    raw_session_id: str | None,
    org_id: str,
    team_id: str = "",
    user_id: str = "",
) -> str | None:
    """Validate or auto-scope a session ID.

    - None → None (no session)
    - Already scoped (contains /) → validate ownership
    - Bare name → auto-scope to org/team/user:name

    Raises ValueError on invalid format or ownership mismatch.
    """
    if raw_session_id is None:
        return None

    import re  # noqa: PLC0415

    if not re.match(r"^[\w/:\-]+$", raw_session_id):
        msg = "Invalid session ID format"
        raise ValueError(msg)

    # Already org-scoped
    if "/" in raw_session_id:
        if not validate_session_ownership(raw_session_id, org_id):
            msg = "Session does not belong to caller's organization"
            raise ValueError(msg)
        return raw_session_id

    # Bare name → auto-scope
    return build_session_id(org_id, team_id or "_", user_id or "_", raw_session_id)


class InMemorySessionStore:
    """In-memory session store for testing and local dev."""

    def __init__(self, config: SessionConfig | None = None) -> None:
        self._config = config or SessionConfig()
        # {session_id: [(seq, role, content, timestamp)]}
        self._sessions: dict[str, list[tuple[int, str, str, float]]] = defaultdict(list)
        self._next_seq: dict[str, int] = defaultdict(int)
        self._titles: dict[str, str] = {}

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        max_msgs = max_messages or self._config.max_messages
        ttl = ttl_seconds or self._config.ttl_seconds
        cutoff = time.time() - ttl

        entries = self._sessions.get(session_id, [])
        # Filter by TTL
        valid = [(seq, role, content, ts) for seq, role, content, ts in entries if ts >= cutoff]
        # Take most recent
        valid.sort(key=lambda x: x[0])
        valid = valid[-max_msgs:]

        return [{"role": role, "content": content} for _, role, content, _ in valid]

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> None:
        """Append messages to session history."""
        now = time.time()
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role not in ("user", "assistant"):
                continue
            if not isinstance(content, str):
                continue
            seq = self._next_seq[session_id]
            self._next_seq[session_id] = seq + 1
            self._sessions[session_id].append((seq, role, content, now))

            # Auto-generate title from first user message
            if role == "user" and session_id not in self._titles and content:
                title = content[:60]
                if len(content) > 60:
                    title += "..."
                self._titles[session_id] = title

        # Prune on write
        ttl = self._config.ttl_seconds
        cutoff = now - ttl
        entries = self._sessions[session_id]
        self._sessions[session_id] = [e for e in entries if e[3] >= cutoff]

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        self._sessions.pop(session_id, None)
        self._next_seq.pop(session_id, None)
        self._titles.pop(session_id, None)

    def _extract_user_id(self, session_id: str) -> str:
        """Extract user_id from session ID format: org/team/user:name."""
        parts = session_id.split("/", 2)
        if len(parts) < 3:
            return ""
        return parts[2].split(":")[0]

    async def list_sessions(
        self,
        *,
        user_id: str,
        org_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sessions for a user within an org, sorted by last message desc.

        Returns list of dicts with: session_id, title, started_at,
        last_message_at, message_count.
        """
        results: list[dict[str, Any]] = []

        for sid, entries in self._sessions.items():
            if not validate_session_ownership(sid, org_id):
                continue
            if self._extract_user_id(sid) != user_id:
                continue
            if not entries:
                continue

            started_at = entries[0][3]
            last_message_at = entries[-1][3]
            title = self._titles.get(sid, "Untitled")

            results.append(
                {
                    "session_id": sid,
                    "title": title,
                    "started_at": started_at,
                    "last_message_at": last_message_at,
                    "message_count": len(entries),
                }
            )

        # Sort by last_message_at descending (most recent first)
        results.sort(key=lambda x: x["last_message_at"], reverse=True)

        # Apply offset and limit
        return results[offset : offset + limit]

    async def search_sessions(
        self,
        *,
        user_id: str,
        org_id: str,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search session content for query substring (case-insensitive).

        Returns matching sessions with snippet context.
        """
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        for sid, entries in self._sessions.items():
            if not validate_session_ownership(sid, org_id):
                continue
            if self._extract_user_id(sid) != user_id:
                continue
            if not entries:
                continue

            # Search all message content for the query
            snippet = ""
            for _seq, _role, content, _ts in entries:
                idx = content.lower().find(query_lower)
                if idx >= 0:
                    # Build snippet: up to 40 chars before and after match
                    start = max(0, idx - 40)
                    end = min(len(content), idx + len(query) + 40)
                    snippet = content[start:end]
                    break

            if not snippet:
                continue

            title = self._titles.get(sid, "Untitled")
            results.append(
                {
                    "session_id": sid,
                    "title": title,
                    "snippet": snippet,
                    "last_message_at": entries[-1][3],
                    "message_count": len(entries),
                }
            )

        # Sort by recency
        results.sort(key=lambda x: x["last_message_at"], reverse=True)
        return results[:limit]
