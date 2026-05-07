"""Working memory: a small, self-editable scratch space.

Distinct from the autonoetic memory tiers (OBSERVATION..WISDOM), working
memory is ephemeral active attention. The self maintains it via the
periodic working-memory-maintenance reflection loop; the operator never
writes to it (operator controls the *base prompt* instead, which is
separately configured and immutable at runtime by the self).

Bounded:
- Max WORKING_MEMORY_MAX_ENTRIES entries (default 10).
- Max WORKING_MEMORY_MAX_CONTENT_LEN characters per entry (default 300).

Eviction on insert when over capacity: lowest (priority, oldest) wins.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4


WORKING_MEMORY_MAX_ENTRIES: int = 10
WORKING_MEMORY_MAX_CONTENT_LEN: int = 300


@dataclass(frozen=True)
class WorkingMemoryEntry:
    entry_id: str
    self_id: str
    content: str
    priority: float
    created_at: datetime
    updated_at: datetime


class WorkingMemory:
    """Thin wrapper over the `working_memory` table."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def entries(self, self_id: str) -> list[WorkingMemoryEntry]:
        cur = self._conn.execute(
            "SELECT entry_id, self_id, content, priority, created_at, "
            "updated_at FROM working_memory "
            "WHERE self_id = ? "
            "ORDER BY priority DESC, created_at ASC",
            (self_id,),
        )
        return [
            WorkingMemoryEntry(
                entry_id=row[0],
                self_id=row[1],
                content=row[2],
                priority=row[3],
                created_at=datetime.fromisoformat(row[4]),
                updated_at=datetime.fromisoformat(row[5]),
            )
            for row in cur.fetchall()
        ]

    def add(
        self,
        self_id: str,
        content: str,
        *,
        priority: float = 0.5,
        max_entries: int = WORKING_MEMORY_MAX_ENTRIES,
    ) -> str:
        if not content.strip():
            raise ValueError("working-memory content cannot be empty")
        if not 0.0 <= priority <= 1.0:
            raise ValueError("priority must be in [0.0, 1.0]")
        truncated = content[:WORKING_MEMORY_MAX_CONTENT_LEN]
        entry_id = str(uuid4())
        now_iso = datetime.now(UTC).isoformat()
        self._conn.execute(
            "INSERT INTO working_memory "
            "(entry_id, self_id, content, priority, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (entry_id, self_id, truncated, priority, now_iso, now_iso),
        )
        self._conn.commit()
        self._evict_over_capacity(self_id, max_entries)
        return entry_id

    def remove(self, self_id: str, entry_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM working_memory WHERE self_id = ? AND entry_id = ?",
            (self_id, entry_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_priority(
        self, self_id: str, entry_id: str, *, priority: float
    ) -> bool:
        if not 0.0 <= priority <= 1.0:
            raise ValueError("priority must be in [0.0, 1.0]")
        now_iso = datetime.now(UTC).isoformat()
        cur = self._conn.execute(
            "UPDATE working_memory "
            "SET priority = ?, updated_at = ? "
            "WHERE self_id = ? AND entry_id = ?",
            (priority, now_iso, self_id, entry_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self, self_id: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM working_memory WHERE self_id = ?", (self_id,)
        )
        self._conn.commit()
        return cur.rowcount

    def render(self, self_id: str) -> str:
        """Human-readable single-block representation for prompt inclusion."""
        items = self.entries(self_id)
        if not items:
            return "_(working memory is empty)_"
        lines: list[str] = []
        for entry in items:
            prefix = "★" if entry.priority >= 0.75 else "·"
            lines.append(f"{prefix} {entry.content}")
        return "\n".join(lines)

    def _evict_over_capacity(self, self_id: str, max_entries: int) -> None:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM working_memory WHERE self_id = ?",
            (self_id,),
        )
        total = int(cur.fetchone()[0])
        overflow = total - max_entries
        if overflow <= 0:
            return
        # Lowest priority + oldest created_at gets evicted first.
        rows = self._conn.execute(
            "SELECT entry_id FROM working_memory WHERE self_id = ? "
            "ORDER BY priority ASC, created_at ASC LIMIT ?",
            (self_id, overflow),
        ).fetchall()
        for (entry_id,) in rows:
            self._conn.execute(
                "DELETE FROM working_memory WHERE entry_id = ?", (entry_id,)
            )
        self._conn.commit()
