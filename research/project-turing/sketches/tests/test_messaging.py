"""Tests for messaging provider (SignalWire SMS, gated by contacts)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
import yaml

from turing.runtime.providers.messaging import (
    ContactNotAllowed,
    DailyLimitExceeded,
    MessagingProvider,
    OutsideAllowedHours,
    SendFailed,
)


def _write_contacts(tmp_path, contacts):
    data = {"contacts": []}
    for c in contacts:
        data["contacts"].append(
            {
                "id": c[0],
                "name": c[1],
                "phone": c[2],
                "allowed": c[3],
                "max_daily_messages": c[4],
                "allowed_hours": list(c[5]),
            }
        )
    p = tmp_path / "contacts.yaml"
    p.write_text(yaml.dump(data))
    return str(p)


def _make_provider(tmp_path, conn, *, responses=None):
    contacts_path = _write_contacts(
        tmp_path,
        [
            ("blake", "Blake", "+15551234567", True, 3, (8, 22)),
            ("alice", "Alice", "+15559876543", False, 1, (9, 20)),
            ("bob", "Bob", "+15555551234", True, 0, (0, 24)),
        ],
    )
    responses = responses or [httpx.Response(201, json={"sid": "SM-test-1"})]

    def handler(request):
        return responses.pop(0)

    transport = httpx.MockTransport(handler)
    provider = MessagingProvider(
        space_url="test.signalwire.com",
        project_id="test-project",
        api_token="test-token",
        from_number="+15550000000",
        contacts_path=contacts_path,
        conn=conn,
        self_id="self-test",
    )
    provider._http = httpx.Client(transport=transport)
    return provider, responses


@pytest.fixture
def conn():
    import sqlite3

    c = sqlite3.connect(":memory:")
    yield c
    c.close()


class TestContactGating:
    def test_msg1_allowed_contact_succeeds(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            msg_id = provider.send("blake", "Hey, I figured out something cool about X")
        assert msg_id.startswith("msg-")
        rows = conn.execute(
            "SELECT COUNT(*) FROM outbound_messages WHERE contact_id = 'blake'"
        ).fetchone()[0]
        assert rows == 1

    def test_msg2_unknown_contact_rejected(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with pytest.raises(ContactNotAllowed):
            provider.send("unknown-person", "Hello")

    def test_msg3_disallowed_contact_rejected(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with pytest.raises(ContactNotAllowed):
            provider.send("alice", "Hello")


class TestDailyLimit:
    def test_msg4_daily_limit_blocks(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        now = datetime(2026, 1, 1, 14, 0, tzinfo=UTC).isoformat()
        for i in range(3):
            conn.execute(
                "INSERT INTO outbound_messages (message_id, self_id, contact_id, provider_sid, body, status, created_at) "
                "VALUES (?, 'self-test', 'blake', 'SM-x', 'msg', 'sent', ?)",
                (f"msg-existing-{i}", now),
            )
            conn.commit()
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            with pytest.raises(DailyLimitExceeded):
                provider.send("blake", "One more thing")

    def test_msg5_zero_daily_limit_blocks(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            with pytest.raises(DailyLimitExceeded):
                provider.send("bob", "Hey")


class TestAllowedHours:
    def test_msg6_blocked_outside_hours(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            with pytest.raises(OutsideAllowedHours):
                provider.send("blake", "Can't sleep?")

    def test_msg7_allowed_during_hours(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            msg_id = provider.send("blake", "Good morning")
        assert msg_id.startswith("msg-")


class TestMessageBody:
    def test_msg8_truncated_to_320(self, tmp_path, conn):
        long_body = "A" * 400
        captured = {}

        def handler(request):
            captured["body"] = request.content.decode()
            return httpx.Response(201, json={"sid": "SM-trunc"})

        transport = httpx.MockTransport(handler)
        provider, _ = _make_provider(tmp_path, conn)
        provider._http = httpx.Client(transport=transport)
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            provider.send("blake", long_body)
        assert f"Body={'A' * 320}" in captured["body"]
        assert "Body=" + "A" * 321 not in captured["body"]

    def test_msg9_empty_body_rejected(self, tmp_path, conn):
        provider, _ = _make_provider(tmp_path, conn)
        with pytest.raises(ValueError):
            provider.send("blake", "")


class TestSignalWireAPI:
    def test_msg10_success_returns_message_id(self, tmp_path, conn):
        provider, _ = _make_provider(
            tmp_path,
            conn,
            responses=[httpx.Response(201, json={"sid": "SM-123"})],
        )
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            msg_id = provider.send("blake", "Test")
        assert msg_id.startswith("msg-")
        row = conn.execute(
            "SELECT provider_sid FROM outbound_messages WHERE message_id = ?", (msg_id,)
        ).fetchone()
        assert row[0] == "SM-123"

    def test_msg11_auth_failure_raises(self, tmp_path, conn):
        provider, _ = _make_provider(
            tmp_path,
            conn,
            responses=[httpx.Response(401, text="Unauthorized")],
        )
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            with pytest.raises(SendFailed):
                provider.send("blake", "Test")
        rows = conn.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0]
        assert rows == 0


class TestIdempotency:
    def test_msg12_idempotency_key_header(self, tmp_path, conn):
        captured = {}

        def handler(request):
            captured["idempotency"] = request.headers.get("Idempotency-Key", "")
            return httpx.Response(201, json={"sid": "SM-idem"})

        transport = httpx.MockTransport(handler)
        provider, _ = _make_provider(tmp_path, conn)
        provider._http = httpx.Client(transport=transport)
        with patch("turing.runtime.providers.messaging.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)
            mock_dt.side_effect = lambda *a, **kw: datetime.now(UTC)
            provider.send("blake", "Test")
        assert re.match(r"msg-[\w-]+", captured["idempotency"])
