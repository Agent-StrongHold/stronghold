"""Audit query engine: filtering, stats aggregation, CSV export over AuditLog protocol."""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from stronghold.protocols.memory import AuditLog
    from stronghold.types.security import AuditEntry


class AuditQueryEngine:
    """Wraps AuditLog protocol with rich filtering, stats, and CSV export."""

    def __init__(self, audit_log: AuditLog) -> None:
        self._audit_log = audit_log

    async def query(
        self,
        *,
        org_id: str = "",
        user_id: str | None = None,
        boundary: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query audit entries with filtering by org, user, boundary, and time."""
        # Fetch from underlying store (org + user scoped)
        entries = await self._audit_log.get_entries(
            user_id=user_id,
            org_id=org_id,
            limit=0,  # get all, we'll filter + limit ourselves
        )
        # If underlying store doesn't support limit=0 for "all", use a large number
        if not entries:
            entries = await self._audit_log.get_entries(
                user_id=user_id,
                org_id=org_id,
                limit=10_000,
            )

        # Apply boundary filter
        if boundary:
            entries = [e for e in entries if e.boundary == boundary]

        # Apply since filter
        if since:
            entries = [e for e in entries if e.timestamp >= since]

        # Apply limit
        return entries[:limit]

    async def stats(
        self,
        *,
        org_id: str = "",
        since: datetime | None = None,
    ) -> dict[str, Any]:
        """Aggregate stats: entries per boundary, per user, per hour."""
        entries = await self.query(org_id=org_id, since=since, limit=10_000)

        per_boundary: Counter[str] = Counter()
        per_user: Counter[str] = Counter()
        per_hour: Counter[str] = Counter()
        per_verdict: Counter[str] = Counter()

        for entry in entries:
            per_boundary[entry.boundary] += 1
            per_user[entry.user_id] += 1
            hour_key = entry.timestamp.strftime("%Y-%m-%dT%H:00:00Z")
            per_hour[hour_key] += 1
            per_verdict[entry.verdict] += 1

        return {
            "total": len(entries),
            "per_boundary": dict(per_boundary.most_common()),
            "per_user": dict(per_user.most_common()),
            "per_hour": dict(sorted(per_hour.items())),
            "per_verdict": dict(per_verdict.most_common()),
        }

    async def export_csv(
        self,
        *,
        org_id: str = "",
        user_id: str | None = None,
        boundary: str | None = None,
        since: datetime | None = None,
        limit: int = 10_000,
    ) -> str:
        """Export audit entries as CSV string."""
        entries = await self.query(
            org_id=org_id,
            user_id=user_id,
            boundary=boundary,
            since=since,
            limit=limit,
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "timestamp",
                "boundary",
                "user_id",
                "org_id",
                "team_id",
                "agent_id",
                "tool_name",
                "verdict",
                "trace_id",
                "request_id",
                "detail",
            ]
        )
        for entry in entries:
            writer.writerow(
                [
                    entry.timestamp.isoformat(),
                    entry.boundary,
                    entry.user_id,
                    entry.org_id,
                    entry.team_id,
                    entry.agent_id,
                    entry.tool_name or "",
                    entry.verdict,
                    entry.trace_id,
                    entry.request_id,
                    entry.detail,
                ]
            )

        return output.getvalue()
