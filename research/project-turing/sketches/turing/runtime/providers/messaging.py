"""MessagingProvider: gated SMS via SignalWire REST API.

Only sends to contacts in the whitelist config. Enforces daily message
limits and allowed-hours windows. Logs every send to SQLite.

SignalWire exposes a Twilio-compatible REST API:
  POST https://{space}.signalwire.com/api/laml/2010-04-01/Accounts/{sid}/Messages.json
  Body: To=+1...&From=+1...&Body=text
  Auth: Basic {sid}:{token}
"""

from __future__ import annotations

import base64
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import yaml


logger = logging.getLogger("turing.providers.messaging")


@dataclass
class Contact:
    id: str
    name: str
    phone: str
    relationship: str
    allowed: bool
    max_daily_messages: int
    allowed_hours: tuple[int, int]


class ContactNotAllowed(Exception):
    pass


class DailyLimitExceeded(Exception):
    pass


class OutsideAllowedHours(Exception):
    pass


class SendFailed(Exception):
    pass


def load_contacts(path: str) -> dict[str, Contact]:
    with open(path) as f:
        data = yaml.safe_load(f)
    contacts: dict[str, Contact] = {}
    for entry in data.get("contacts", []):
        hours = entry.get("allowed_hours", [0, 24])
        contacts[entry["id"]] = Contact(
            id=entry["id"],
            name=entry["name"],
            phone=entry["phone"],
            relationship=entry.get("relationship", "unknown"),
            allowed=entry.get("allowed", False),
            max_daily_messages=entry.get("max_daily_messages", 1),
            allowed_hours=(hours[0], hours[1]),
        )
    return contacts


class MessagingProvider:
    def __init__(
        self,
        *,
        space_url: str,
        project_id: str,
        api_token: str,
        from_number: str,
        contacts_path: str,
        conn: sqlite3.Connection,
        self_id: str,
    ) -> None:
        self._base_url = (
            f"https://{space_url}/api/laml/2010-04-01/Accounts/{project_id}/Messages.json"
        )
        cred = base64.b64encode(f"{project_id}:{api_token}".encode()).decode()
        self._auth_header = f"Basic {cred}"
        self._from = from_number
        self._contacts = load_contacts(contacts_path)
        self._conn = conn
        self._self_id = self_id
        self._http = httpx.Client(timeout=30.0)
        self._ensure_table()
        logger.info(
            "messaging provider initialized: %d contacts, from=%s, space=%s",
            len(self._contacts),
            from_number,
            space_url,
        )

    def _ensure_table(self) -> None:
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS outbound_messages ("
            "message_id TEXT PRIMARY KEY, self_id TEXT NOT NULL, "
            "contact_id TEXT NOT NULL, provider_sid TEXT, "
            "body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'sent', "
            "created_at TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_outbound_contact_date "
            "ON outbound_messages (contact_id, created_at DESC)"
        )
        self._conn.commit()

    def contacts(self) -> dict[str, Contact]:
        return dict(self._contacts)

    def daily_count(self, contact_id: str) -> int:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COUNT(*) FROM outbound_messages WHERE contact_id = ? AND created_at LIKE ?",
            (contact_id, f"{today}%"),
        ).fetchone()
        return int(row[0])

    def _within_hours(self, contact: Contact) -> bool:
        now = datetime.now(UTC)
        if contact.allowed_hours == (0, 24):
            return True
        return contact.allowed_hours[0] <= now.hour < contact.allowed_hours[1]

    def send(self, contact_id: str, body: str) -> str:
        if not body or not body.strip():
            raise ValueError("message body cannot be empty")
        contact = self._contacts.get(contact_id)
        if contact is None:
            raise ContactNotAllowed(f"unknown contact: {contact_id}")
        if not contact.allowed:
            raise ContactNotAllowed(f"contact {contact_id} is not allowed")
        if not self._within_hours(contact):
            raise OutsideAllowedHours(
                f"current hour outside {contact.allowed_hours} for {contact_id}"
            )
        if self.daily_count(contact_id) >= contact.max_daily_messages:
            raise DailyLimitExceeded(
                f"contact {contact_id} already at {contact.max_daily_messages} messages today"
            )

        truncated = body.strip()[:320]
        message_id = f"msg-{uuid4()}"
        resp = self._http.post(
            self._base_url,
            data={"To": contact.phone, "From": self._from, "Body": truncated},
            headers={
                "Authorization": self._auth_header,
                "Content-Type": "application/x-www-form-urlencoded",
                "Idempotency-Key": message_id,
            },
        )
        if resp.status_code >= 300:
            logger.error("signalwire send failed: %d %s", resp.status_code, resp.text[:200])
            raise SendFailed(f"SignalWire {resp.status_code}: {resp.text[:200]}")

        provider_sid = resp.json().get("sid", "")
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO outbound_messages (message_id, self_id, contact_id, provider_sid, body, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'sent', ?)",
            (message_id, self._self_id, contact_id, provider_sid, truncated, now),
        )
        self._conn.commit()
        logger.info("sent SMS to %s (%s): %s", contact_id, contact.name, truncated[:60])
        return message_id

    def get_contact(self, contact_id: str) -> Contact | None:
        return self._contacts.get(contact_id)
