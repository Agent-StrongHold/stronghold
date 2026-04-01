"""Tests for the notification dispatcher — routes events to channels."""
from __future__ import annotations

import httpx
import pytest
import respx

from stronghold.notifications.channels import (
    DiscordChannel,
    GenericWebhookChannel,
    Notification,
    SlackChannel,
)
from stronghold.notifications.dispatcher import NotificationDispatcher


class TestDispatcherRegistration:
    def test_register_channel(self) -> None:
        d = NotificationDispatcher()
        ch = GenericWebhookChannel(webhook_url="https://example.com/hook")
        d.register("warden_block", ch)
        # No error means success; internal state verified by dispatch tests

    def test_register_multiple_channels_same_event(self) -> None:
        d = NotificationDispatcher()
        ch1 = SlackChannel(webhook_url="https://hooks.slack.com/a")
        ch2 = DiscordChannel(webhook_url="https://discord.com/api/webhooks/1/x")
        d.register("warden_block", ch1)
        d.register("warden_block", ch2)
        # Both should be stored — verified by dispatch test below


class TestDispatcherRouting:
    @respx.mock
    async def test_dispatch_to_single_channel(self) -> None:
        url = "https://example.com/hook"
        respx.post(url).mock(return_value=httpx.Response(200))
        d = NotificationDispatcher()
        ch = GenericWebhookChannel(webhook_url=url)
        d.register("circuit_open", ch)
        n = Notification(event_type="circuit_open", title="Breaker tripped")
        results = await d.dispatch(n)
        assert len(results) == 1
        assert all(results.values())

    @respx.mock
    async def test_dispatch_to_multiple_channels(self) -> None:
        slack_url = "https://hooks.slack.com/services/T/B/X"
        discord_url = "https://discord.com/api/webhooks/1/x"
        respx.post(slack_url).mock(return_value=httpx.Response(200))
        respx.post(discord_url).mock(return_value=httpx.Response(204))
        d = NotificationDispatcher()
        d.register("warden_block", SlackChannel(webhook_url=slack_url))
        d.register("warden_block", DiscordChannel(webhook_url=discord_url))
        n = Notification(event_type="warden_block", title="Blocked")
        results = await d.dispatch(n)
        assert len(results) == 2
        assert all(results.values())

    @respx.mock
    async def test_dispatch_partial_failure(self) -> None:
        ok_url = "https://example.com/ok"
        fail_url = "https://example.com/fail"
        respx.post(ok_url).mock(return_value=httpx.Response(200))
        respx.post(fail_url).mock(return_value=httpx.Response(500))
        d = NotificationDispatcher()
        d.register("quota_warning", GenericWebhookChannel(webhook_url=ok_url))
        d.register("quota_warning", GenericWebhookChannel(webhook_url=fail_url))
        n = Notification(event_type="quota_warning")
        results = await d.dispatch(n)
        assert len(results) == 2
        successes = [v for v in results.values()]
        assert True in successes
        assert False in successes

    async def test_dispatch_unregistered_event(self) -> None:
        d = NotificationDispatcher()
        n = Notification(event_type="unknown_event")
        results = await d.dispatch(n)
        assert results == {}

    @respx.mock
    async def test_dispatch_does_not_send_to_wrong_event(self) -> None:
        url = "https://example.com/hook"
        route = respx.post(url).mock(return_value=httpx.Response(200))
        d = NotificationDispatcher()
        d.register("warden_block", GenericWebhookChannel(webhook_url=url))
        n = Notification(event_type="quota_warning")
        results = await d.dispatch(n)
        assert results == {}
        assert route.call_count == 0

    @respx.mock
    async def test_dispatch_multiple_event_types(self) -> None:
        url1 = "https://example.com/hook1"
        url2 = "https://example.com/hook2"
        respx.post(url1).mock(return_value=httpx.Response(200))
        respx.post(url2).mock(return_value=httpx.Response(200))
        d = NotificationDispatcher()
        d.register("warden_block", GenericWebhookChannel(webhook_url=url1))
        d.register("quota_warning", GenericWebhookChannel(webhook_url=url2))

        n1 = Notification(event_type="warden_block")
        r1 = await d.dispatch(n1)
        assert len(r1) == 1

        n2 = Notification(event_type="quota_warning")
        r2 = await d.dispatch(n2)
        assert len(r2) == 1
