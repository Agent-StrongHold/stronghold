"""Session-to-episodic memory bridge.

Summarizes expired sessions and stores them as low-weight episodic memories.
Runs as a background Reactor interval trigger.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from stronghold.types.memory import EpisodicMemory, MemoryScope, MemoryTier

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.memory import EpisodicStore, SessionStore
    from stronghold.sessions.store import InMemorySessionStore

logger = logging.getLogger("stronghold.sessions.bridge")

# Minimum user messages to warrant summarization (skip trivial sessions)
MIN_MESSAGES_FOR_BRIDGE = 3
# Weight for bridged memories (Observation tier)
BRIDGE_MEMORY_WEIGHT = 0.2


class SessionBridge:
    """Bridge expired sessions to episodic memory."""

    def __init__(
        self,
        session_store: SessionStore,
        episodic_store: EpisodicStore,
        llm: LLMClient | None = None,
        *,
        session_ttl: float = 86400.0,  # 24 hours default
    ) -> None:
        self._sessions = session_store
        self._episodic = episodic_store
        self._llm = llm
        self._ttl = session_ttl
        self._bridged: set[str] = set()  # already bridged session IDs

    async def sweep(self) -> int:
        """Scan for expired sessions, summarize, and bridge to episodic memory.

        Returns count of sessions bridged.

        This accesses InMemorySessionStore internals (_sessions) to enumerate
        sessions and check timestamps. A production PostgreSQL store would use
        a SQL query instead.
        """
        store: InMemorySessionStore = self._sessions  # type: ignore[assignment]
        bridged_count = 0

        for session_id in list(store._sessions.keys()):
            if session_id in self._bridged:
                continue

            entries = store._sessions.get(session_id, [])
            if not entries:
                continue

            # Check if the most recent message is expired
            last_ts = max(ts for _, _, _, ts in entries)
            if not self._is_expired(last_ts):
                continue

            # Build message dicts from raw entries
            messages = [
                {"role": role, "content": content}
                for _, role, content, _ in sorted(entries, key=lambda e: e[0])
            ]

            # Parse identity from session_id
            parsed = self._parse_session_id(session_id)
            ok = await self.bridge_session(
                session_id,
                messages,
                org_id=parsed.get("org_id", ""),
                user_id=parsed.get("user_id", ""),
            )
            if ok:
                bridged_count += 1

        return bridged_count

    async def bridge_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        org_id: str = "",
        user_id: str = "",
    ) -> bool:
        """Summarize a single session and store as episodic memory.

        Returns True if successfully bridged, False if skipped.
        """
        # Don't re-bridge
        if session_id in self._bridged:
            return False

        # Count user messages — skip trivial sessions
        user_msgs = [m for m in messages if m.get("role") == "user"]
        if len(user_msgs) < MIN_MESSAGES_FOR_BRIDGE:
            return False

        # Generate summary
        summary = await self._summarize(messages)
        if not summary:
            return False

        # Parse identity from session_id if not provided
        if not user_id:
            parsed = self._parse_session_id(session_id)
            org_id = org_id or parsed.get("org_id", "")
            user_id = parsed.get("user_id", "")

        # Create and store episodic memory
        memory = EpisodicMemory(
            memory_id=str(uuid.uuid4()),
            tier=MemoryTier.OBSERVATION,
            content=summary,
            weight=BRIDGE_MEMORY_WEIGHT,
            org_id=org_id,
            user_id=user_id,
            scope=MemoryScope.USER if user_id else MemoryScope.TEAM,
            source=f"session_summary:{session_id}",
            context={"session_id": session_id},
        )

        await self._episodic.store(memory)
        self._bridged.add(session_id)

        logger.info(
            "Session %s bridged → episodic %s (user=%s)",
            session_id,
            memory.memory_id,
            user_id,
        )
        return True

    def _is_expired(self, last_message_time: float) -> bool:
        """Check if a session has exceeded TTL."""
        return (time.time() - last_message_time) > self._ttl

    async def _summarize(self, messages: list[dict[str, Any]]) -> str:
        """Generate a summary of the conversation.

        If LLM is available, use it. Otherwise, extract key user messages.
        """
        if self._llm is None:
            # Fallback: concatenate user messages, truncate
            user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
            return f"Session summary: {'; '.join(str(m)[:100] for m in user_msgs[:5])}"

        summary_prompt: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "Summarize this conversation in 2-3 sentences. "
                    "Focus on: user preferences, decisions made, key facts learned. "
                    "Ignore greetings and chit-chat."
                ),
            },
            *messages[-20:],  # last 20 messages to stay within context
        ]
        try:
            response = await self._llm.complete(summary_prompt, "auto")
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return str(content) if content else "No summary generated."
        except Exception:
            logger.warning("Session bridge LLM call failed", exc_info=True)
            # Fall back to deterministic summary
            user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
            return f"Session summary: {'; '.join(str(m)[:100] for m in user_msgs[:5])}"

    @staticmethod
    def _parse_session_id(session_id: str) -> dict[str, str]:
        """Parse identity from session_id format: 'org/team/user:session_name'.

        Also handles simpler formats like 'user:session' or just 'session'.
        """
        result: dict[str, str] = {}
        parts = session_id.split(":", 1)
        identity = parts[0]

        segments = identity.split("/")
        if len(segments) >= 3:  # noqa: PLR2004
            result["org_id"] = segments[0]
            result["team_id"] = segments[1]
            result["user_id"] = segments[2]
        elif len(segments) == 2:  # noqa: PLR2004
            result["team_id"] = segments[0]
            result["user_id"] = segments[1]
        elif len(segments) == 1 and segments[0]:
            result["user_id"] = segments[0]

        return result
