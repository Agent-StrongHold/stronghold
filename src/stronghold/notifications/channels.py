"""Outbound notification channels — Slack, Discord, Teams, generic webhook."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("stronghold.notifications")


@dataclass
class Notification:
    """An outbound notification triggered by a Stronghold event."""

    event_type: str  # "warden_block", "circuit_open", "quota_warning", etc.
    title: str = ""
    detail: str = ""
    severity: str = "info"  # info, warning, error, critical
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationChannel(ABC):
    """Base class for outbound notification channels."""

    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Send a notification. Returns True on success."""
        ...

    @abstractmethod
    def format_message(self, notification: Notification) -> dict[str, Any]:
        """Format a notification for this channel's wire format."""
        ...


_SLACK_COLORS: dict[str, str] = {
    "info": "#36a64f",
    "warning": "#ff9900",
    "error": "#ff0000",
    "critical": "#8b0000",
}


class SlackChannel(NotificationChannel):
    """Posts notifications to a Slack incoming webhook."""

    def __init__(self, webhook_url: str, channel: str = "") -> None:
        self._url = webhook_url
        self._channel = channel

    def format_message(self, n: Notification) -> dict[str, Any]:
        color = _SLACK_COLORS.get(n.severity, "#808080")
        return {
            "attachments": [
                {
                    "color": color,
                    "title": n.title,
                    "text": n.detail,
                    "fields": [
                        {"title": k, "value": str(v), "short": True} for k, v in n.metadata.items()
                    ],
                }
            ]
        }

    async def send(self, notification: Notification) -> bool:
        import httpx  # noqa: PLC0415

        msg = self.format_message(notification)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._url, json=msg)
                return resp.status_code == 200
        except Exception:
            logger.warning("Slack notification failed", exc_info=True)
            return False


_DISCORD_COLORS: dict[str, int] = {
    "info": 0x36A64F,
    "warning": 0xFF9900,
    "error": 0xFF0000,
    "critical": 0x8B0000,
}


class DiscordChannel(NotificationChannel):
    """Posts notifications to a Discord webhook."""

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    def format_message(self, n: Notification) -> dict[str, Any]:
        color = _DISCORD_COLORS.get(n.severity, 0x808080)
        return {
            "embeds": [
                {
                    "title": n.title,
                    "description": n.detail,
                    "color": color,
                    "fields": [
                        {"name": k, "value": str(v), "inline": True} for k, v in n.metadata.items()
                    ],
                }
            ]
        }

    async def send(self, notification: Notification) -> bool:
        import httpx  # noqa: PLC0415

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._url, json=self.format_message(notification))
                return 200 <= resp.status_code < 300
        except Exception:
            logger.warning("Discord notification failed", exc_info=True)
            return False


class GenericWebhookChannel(NotificationChannel):
    """Posts notifications as plain JSON to any HTTP endpoint."""

    def __init__(self, webhook_url: str) -> None:
        self._url = webhook_url

    def format_message(self, n: Notification) -> dict[str, Any]:
        return {
            "event_type": n.event_type,
            "title": n.title,
            "detail": n.detail,
            "severity": n.severity,
            "metadata": n.metadata,
        }

    async def send(self, notification: Notification) -> bool:
        import httpx  # noqa: PLC0415

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(self._url, json=self.format_message(notification))
                return 200 <= resp.status_code < 300
        except Exception:
            logger.warning("Webhook notification failed", exc_info=True)
            return False
