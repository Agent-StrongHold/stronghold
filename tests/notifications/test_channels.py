"""Tests for outbound notification channels — Slack, Discord, generic webhook."""
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


# ── Notification dataclass defaults ─────────────────────────────────


class TestNotificationDefaults:
    def test_minimal_notification(self) -> None:
        n = Notification(event_type="warden_block")
        assert n.event_type == "warden_block"
        assert n.title == ""
        assert n.detail == ""
        assert n.severity == "info"
        assert n.metadata == {}

    def test_full_notification(self) -> None:
        n = Notification(
            event_type="circuit_open",
            title="Circuit breaker tripped",
            detail="Trigger 'quota_check' disabled after 3 failures",
            severity="critical",
            metadata={"trigger": "quota_check", "failures": 3},
        )
        assert n.event_type == "circuit_open"
        assert n.title == "Circuit breaker tripped"
        assert n.severity == "critical"
        assert n.metadata["failures"] == 3


# ── Slack channel ───────────────────────────────────────────────────


class TestSlackChannel:
    def test_format_attachments_with_color(self) -> None:
        ch = SlackChannel(webhook_url="https://hooks.slack.com/services/T/B/X")
        n = Notification(
            event_type="warden_block",
            title="Input blocked",
            detail="Prompt injection detected",
            severity="error",
            metadata={"user": "alice", "score": "0.95"},
        )
        msg = ch.format_message(n)
        assert "attachments" in msg
        att = msg["attachments"][0]
        assert att["color"] == "#ff0000"
        assert att["title"] == "Input blocked"
        assert att["text"] == "Prompt injection detected"
        # Fields should contain metadata
        field_titles = [f["title"] for f in att["fields"]]
        assert "user" in field_titles
        assert "score" in field_titles

    def test_format_info_severity_green(self) -> None:
        ch = SlackChannel(webhook_url="https://hooks.slack.com/services/T/B/X")
        n = Notification(event_type="task_complete", severity="info")
        msg = ch.format_message(n)
        assert msg["attachments"][0]["color"] == "#36a64f"

    def test_format_warning_severity_orange(self) -> None:
        ch = SlackChannel(webhook_url="https://hooks.slack.com/services/T/B/X")
        n = Notification(event_type="quota_warning", severity="warning")
        msg = ch.format_message(n)
        assert msg["attachments"][0]["color"] == "#ff9900"

    def test_format_critical_severity_dark_red(self) -> None:
        ch = SlackChannel(webhook_url="https://hooks.slack.com/services/T/B/X")
        n = Notification(event_type="breach", severity="critical")
        msg = ch.format_message(n)
        assert msg["attachments"][0]["color"] == "#8b0000"

    def test_format_unknown_severity_gray(self) -> None:
        ch = SlackChannel(webhook_url="https://hooks.slack.com/services/T/B/X")
        n = Notification(event_type="test", severity="debug")
        msg = ch.format_message(n)
        assert msg["attachments"][0]["color"] == "#808080"

    @respx.mock
    async def test_send_success(self) -> None:
        url = "https://hooks.slack.com/services/T/B/X"
        respx.post(url).mock(return_value=httpx.Response(200, text="ok"))
        ch = SlackChannel(webhook_url=url)
        n = Notification(event_type="test", title="Hello")
        result = await ch.send(n)
        assert result is True

    @respx.mock
    async def test_send_failure_500(self) -> None:
        url = "https://hooks.slack.com/services/T/B/X"
        respx.post(url).mock(return_value=httpx.Response(500, text="error"))
        ch = SlackChannel(webhook_url=url)
        n = Notification(event_type="test", title="Hello")
        result = await ch.send(n)
        assert result is False

    @respx.mock
    async def test_send_timeout(self) -> None:
        url = "https://hooks.slack.com/services/T/B/X"
        respx.post(url).mock(side_effect=httpx.ConnectTimeout("timeout"))
        ch = SlackChannel(webhook_url=url)
        n = Notification(event_type="test")
        result = await ch.send(n)
        assert result is False


# ── Discord channel ─────────────────────────────────────────────────


class TestDiscordChannel:
    def test_format_embeds(self) -> None:
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/123/abc")
        n = Notification(
            event_type="quota_warning",
            title="Quota at 90%",
            detail="Provider openai approaching limit",
            severity="warning",
            metadata={"provider": "openai", "pct": "90"},
        )
        msg = ch.format_message(n)
        assert "embeds" in msg
        embed = msg["embeds"][0]
        assert embed["title"] == "Quota at 90%"
        assert embed["description"] == "Provider openai approaching limit"
        assert embed["color"] == 0xFF9900
        field_names = [f["name"] for f in embed["fields"]]
        assert "provider" in field_names

    def test_format_error_severity_red(self) -> None:
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/123/abc")
        n = Notification(event_type="error", severity="error")
        msg = ch.format_message(n)
        assert msg["embeds"][0]["color"] == 0xFF0000

    def test_format_unknown_severity_gray(self) -> None:
        ch = DiscordChannel(webhook_url="https://discord.com/api/webhooks/123/abc")
        n = Notification(event_type="test", severity="trace")
        msg = ch.format_message(n)
        assert msg["embeds"][0]["color"] == 0x808080

    @respx.mock
    async def test_send_success(self) -> None:
        url = "https://discord.com/api/webhooks/123/abc"
        respx.post(url).mock(return_value=httpx.Response(204))
        ch = DiscordChannel(webhook_url=url)
        n = Notification(event_type="test", title="Hello")
        result = await ch.send(n)
        assert result is True

    @respx.mock
    async def test_send_failure_500(self) -> None:
        url = "https://discord.com/api/webhooks/123/abc"
        respx.post(url).mock(return_value=httpx.Response(500, text="error"))
        ch = DiscordChannel(webhook_url=url)
        n = Notification(event_type="test")
        result = await ch.send(n)
        assert result is False

    @respx.mock
    async def test_send_timeout(self) -> None:
        url = "https://discord.com/api/webhooks/123/abc"
        respx.post(url).mock(side_effect=httpx.ReadTimeout("timeout"))
        ch = DiscordChannel(webhook_url=url)
        n = Notification(event_type="test")
        result = await ch.send(n)
        assert result is False


# ── Generic webhook channel ─────────────────────────────────────────


class TestGenericWebhookChannel:
    def test_format_plain_json(self) -> None:
        ch = GenericWebhookChannel(webhook_url="https://example.com/hook")
        n = Notification(
            event_type="circuit_open",
            title="Breaker tripped",
            detail="Trigger disabled",
            severity="critical",
            metadata={"trigger": "quota_check"},
        )
        msg = ch.format_message(n)
        assert msg["event_type"] == "circuit_open"
        assert msg["title"] == "Breaker tripped"
        assert msg["detail"] == "Trigger disabled"
        assert msg["severity"] == "critical"
        assert msg["metadata"]["trigger"] == "quota_check"

    @respx.mock
    async def test_send_success(self) -> None:
        url = "https://example.com/hook"
        respx.post(url).mock(return_value=httpx.Response(200, json={"ok": True}))
        ch = GenericWebhookChannel(webhook_url=url)
        n = Notification(event_type="test")
        result = await ch.send(n)
        assert result is True

    @respx.mock
    async def test_send_failure_500(self) -> None:
        url = "https://example.com/hook"
        respx.post(url).mock(return_value=httpx.Response(500))
        ch = GenericWebhookChannel(webhook_url=url)
        n = Notification(event_type="test")
        result = await ch.send(n)
        assert result is False

    @respx.mock
    async def test_send_timeout(self) -> None:
        url = "https://example.com/hook"
        respx.post(url).mock(side_effect=httpx.ConnectTimeout("timeout"))
        ch = GenericWebhookChannel(webhook_url=url)
        n = Notification(event_type="test")
        result = await ch.send(n)
        assert result is False
