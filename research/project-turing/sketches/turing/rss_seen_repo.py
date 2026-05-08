"""RSS seen-item repository: O(1) dedup that survives restarts.

Wraps the `rss_seen_item` table. Call `is_seen` before processing a feed
item and `mark_seen` after the OBSERVATION is committed. Hydrate the
in-memory RSSReader FeedState on boot via `hydrate_seen_ids`.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


class RssSeenRepo:
    """Thin wrapper over the `rss_seen_item` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def is_seen(self, self_id: str, feed_url: str, item_id: str) -> bool:
        """Return True if this (self_id, feed_url, item_id) triple is recorded."""
        row = self._conn.execute(
            "SELECT 1 FROM rss_seen_item WHERE self_id = ? AND feed_url = ? AND item_id = ?",
            (self_id, feed_url, item_id),
        ).fetchone()
        return row is not None

    def mark_seen(
        self,
        self_id: str,
        feed_url: str,
        item_id: str,
        now: datetime | None = None,
    ) -> None:
        """Record the triple. Idempotent — silently no-ops on conflict."""
        ts = (now or datetime.now(UTC)).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO rss_seen_item (self_id, feed_url, item_id, first_seen_at) "
            "VALUES (?, ?, ?, ?)",
            (self_id, feed_url, item_id, ts),
        )
        self._conn.commit()

    def count(self, self_id: str, feed_url: str) -> int:
        """Return the number of seen items for a given feed."""
        row = self._conn.execute(
            "SELECT COUNT(*) FROM rss_seen_item WHERE self_id = ? AND feed_url = ?",
            (self_id, feed_url),
        ).fetchone()
        return int(row[0]) if row else 0

    def hydrate_seen_ids(self, self_id: str, feed_url: str) -> set[str]:
        """Return all known item_ids for a feed so callers can seed in-memory caches."""
        rows = self._conn.execute(
            "SELECT item_id FROM rss_seen_item WHERE self_id = ? AND feed_url = ?",
            (self_id, feed_url),
        ).fetchall()
        return {row[0] for row in rows}

    def backfill_from_observations(
        self,
        self_id: str,
        feed_url: str,
        observations: list[dict],
    ) -> int:
        """Backfill seen items from OBSERVATION context dicts (migration helper).

        Each dict should have keys ``item_id`` and optionally ``created_at``.
        Returns the number of rows newly inserted.
        """
        now_iso = datetime.now(UTC).isoformat()
        inserted = 0
        for obs in observations:
            item_id = obs.get("item_id")
            if not item_id:
                continue
            ts = obs.get("created_at") or now_iso
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO rss_seen_item (self_id, feed_url, item_id, first_seen_at) "
                "VALUES (?, ?, ?, ?)",
                (self_id, feed_url, item_id, ts),
            )
            inserted += cur.rowcount
        if inserted:
            self._conn.commit()
        return inserted
