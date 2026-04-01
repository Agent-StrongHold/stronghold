"""Notification dispatcher — routes events to configured channels."""

from __future__ import annotations

import logging

from stronghold.notifications.channels import Notification, NotificationChannel  # noqa: TC001

logger = logging.getLogger("stronghold.notifications.dispatcher")


class NotificationDispatcher:
    """Routes notifications to registered channels based on event type."""

    def __init__(self) -> None:
        self._routes: dict[str, list[NotificationChannel]] = {}

    def register(self, event_type: str, channel: NotificationChannel) -> None:
        """Register a channel to receive notifications for a specific event type."""
        if event_type not in self._routes:
            self._routes[event_type] = []
        self._routes[event_type].append(channel)
        logger.info(
            "Registered %s channel for event type '%s'",
            type(channel).__name__,
            event_type,
        )

    async def dispatch(self, notification: Notification) -> dict[str, bool]:
        """Dispatch a notification to all channels registered for its event type.

        Returns a dict mapping channel identifiers to send success/failure.
        """
        channels = self._routes.get(notification.event_type, [])
        if not channels:
            return {}

        results: dict[str, bool] = {}
        for i, channel in enumerate(channels):
            key = f"{type(channel).__name__}_{i}"
            success = await channel.send(notification)
            results[key] = success

        sent = sum(1 for v in results.values() if v)
        logger.info(
            "Dispatched '%s' to %d channels (%d succeeded)",
            notification.event_type,
            len(channels),
            sent,
        )
        return results
