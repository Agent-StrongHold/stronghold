"""Human escalation — transfer stuck requests to operators."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class Escalation:
    """A request escalated from an agent to a human operator."""

    id: str = ""
    session_id: str = ""
    agent_name: str = ""
    user_id: str = ""
    org_id: str = ""
    reason: str = ""  # "max_rounds_exceeded", "user_requested", "warden_block", "timeout"
    context: list[dict[str, Any]] = field(default_factory=list)  # conversation history
    status: str = "pending"  # pending, responded, taken_over, dismissed
    response: str = ""  # human's response
    created_at: float = 0.0
    resolved_at: float = 0.0
    resolved_by: str = ""


class InMemoryEscalationManager:
    """In-memory escalation store for dev/test. Production uses PostgreSQL."""

    def __init__(self) -> None:
        self._escalations: dict[str, Escalation] = {}

    async def escalate(self, escalation: Escalation) -> Escalation:
        """Create a new escalation. Assigns ID and timestamp if missing."""
        if not escalation.id:
            escalation.id = f"esc-{uuid4().hex[:12]}"
        escalation.created_at = time.time()
        escalation.status = "pending"
        self._escalations[escalation.id] = escalation
        return escalation

    async def get(self, esc_id: str, *, org_id: str) -> Escalation | None:
        """Get an escalation by ID, scoped to org."""
        esc = self._escalations.get(esc_id)
        if esc is None or esc.org_id != org_id:
            return None
        return esc

    async def list_pending(self, *, org_id: str) -> list[Escalation]:
        """List all pending escalations for an org."""
        return [
            esc
            for esc in self._escalations.values()
            if esc.org_id == org_id and esc.status == "pending"
        ]

    async def respond(
        self,
        esc_id: str,
        *,
        org_id: str,
        response: str,
        resolved_by: str,
    ) -> bool:
        """Human provides a response to inject into the conversation."""
        esc = self._escalations.get(esc_id)
        if esc is None or esc.org_id != org_id:
            return False
        if esc.status != "pending":
            return False
        esc.status = "responded"
        esc.response = response
        esc.resolved_at = time.time()
        esc.resolved_by = resolved_by
        return True

    async def takeover(
        self,
        esc_id: str,
        *,
        org_id: str,
        resolved_by: str,
    ) -> bool:
        """Human takes full control of the session."""
        esc = self._escalations.get(esc_id)
        if esc is None or esc.org_id != org_id:
            return False
        if esc.status != "pending":
            return False
        esc.status = "taken_over"
        esc.resolved_at = time.time()
        esc.resolved_by = resolved_by
        return True

    async def dismiss(
        self,
        esc_id: str,
        *,
        org_id: str,
        resolved_by: str,
    ) -> bool:
        """Dismiss escalation — agent retries."""
        esc = self._escalations.get(esc_id)
        if esc is None or esc.org_id != org_id:
            return False
        if esc.status != "pending":
            return False
        esc.status = "dismissed"
        esc.resolved_at = time.time()
        esc.resolved_by = resolved_by
        return True
