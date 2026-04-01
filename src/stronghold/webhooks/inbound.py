"""Inbound webhook processing — external events trigger agent actions.

Dataclasses, in-memory store, and template rendering for inbound webhooks.
External systems push events INTO Stronghold to trigger agent actions via
HMAC-signed HTTP POST requests.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from uuid import uuid4


@dataclass
class WebhookConfig:
    """Configuration for a registered inbound webhook."""

    id: str = ""
    name: str = ""
    org_id: str = ""
    secret: str = ""  # shared secret for HMAC verification
    source: str = ""  # "github", "monitoring", "custom"
    agent: str = ""  # target agent, or "" for auto-classify
    prompt_template: str = ""  # template with {{field}} placeholders
    enabled: bool = True
    created_at: float = 0.0
    call_count: int = 0


@dataclass
class WebhookExecution:
    """Record of a single inbound webhook invocation."""

    id: str = ""
    webhook_id: str = ""
    timestamp: float = 0.0
    status: str = ""  # "success", "error", "rejected"
    detail: str = ""


class InMemoryWebhookStore:
    """In-memory store for webhook configurations and execution history."""

    def __init__(self) -> None:
        self._webhooks: dict[str, WebhookConfig] = {}
        self._executions: dict[str, list[WebhookExecution]] = {}
        # Rate limit tracking: webhook_id -> list of call timestamps
        self._call_timestamps: dict[str, list[float]] = {}

    async def register(self, config: WebhookConfig) -> WebhookConfig:
        """Register a new webhook. Generates ID and secret if not set."""
        if not config.id:
            config.id = str(uuid4())
        if not config.secret:
            config.secret = secrets.token_urlsafe(32)
        self._webhooks[config.id] = config
        return config

    async def get(self, webhook_id: str, *, org_id: str) -> WebhookConfig | None:
        """Get a webhook by ID, scoped to the given org."""
        wh = self._webhooks.get(webhook_id)
        if wh is not None and wh.org_id == org_id:
            return wh
        return None

    async def list_all(self, *, org_id: str) -> list[WebhookConfig]:
        """List all webhooks for the given org."""
        return [wh for wh in self._webhooks.values() if wh.org_id == org_id]

    async def delete(self, webhook_id: str, *, org_id: str) -> bool:
        """Delete a webhook by ID, scoped to the given org. Returns True if deleted."""
        wh = self._webhooks.get(webhook_id)
        if wh is not None and wh.org_id == org_id:
            del self._webhooks[webhook_id]
            self._executions.pop(webhook_id, None)
            self._call_timestamps.pop(webhook_id, None)
            return True
        return False

    async def record_execution(self, webhook_id: str, execution: WebhookExecution) -> None:
        """Record an execution for a webhook."""
        if webhook_id not in self._executions:
            self._executions[webhook_id] = []
        self._executions[webhook_id].append(execution)

    async def get_executions(self, webhook_id: str) -> list[WebhookExecution]:
        """Get all executions for a webhook."""
        return self._executions.get(webhook_id, [])

    async def get_by_id_unsafe(self, webhook_id: str) -> WebhookConfig | None:
        """Get webhook without org check — for inbound processing only."""
        return self._webhooks.get(webhook_id)

    def check_rate_limit(self, webhook_id: str, now: float) -> bool:
        """Check if webhook is within rate limit (60 calls/minute).

        Returns True if allowed, False if rate limited.
        """
        max_calls_per_minute = 60
        window = 60.0

        timestamps = self._call_timestamps.get(webhook_id, [])
        # Prune old timestamps outside the window
        cutoff = now - window
        timestamps = [t for t in timestamps if t > cutoff]
        self._call_timestamps[webhook_id] = timestamps

        return len(timestamps) < max_calls_per_minute

    def record_call(self, webhook_id: str, now: float) -> None:
        """Record a call timestamp for rate limiting."""
        if webhook_id not in self._call_timestamps:
            self._call_timestamps[webhook_id] = []
        self._call_timestamps[webhook_id].append(now)


def render_template(template: str, payload: dict[str, Any]) -> str:
    """Render prompt template with payload fields. Simple {{field}} substitution."""
    result = template
    for key, value in payload.items():
        result = result.replace(f"{{{{{key}}}}}", str(value))
    return result
