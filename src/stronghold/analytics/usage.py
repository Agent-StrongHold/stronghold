"""Per-user usage tracking and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class UsageRecord:
    """A single usage event."""

    user_id: str = ""
    org_id: str = ""
    model: str = ""
    provider: str = ""
    task_type: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: float = 0.0


@dataclass
class UsageSummary:
    """Aggregated usage for a period."""

    user_id: str = ""
    org_id: str = ""
    period: str = ""  # e.g., "2026-03"
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    by_task_type: dict[str, int] = field(default_factory=dict)
    by_model: dict[str, int] = field(default_factory=dict)


class InMemoryUsageTracker:
    """Track per-user usage in memory."""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []

    async def record(self, record: UsageRecord) -> None:
        """Record a usage event."""
        self._records.append(record)

    async def get_summary(self, *, user_id: str, org_id: str, period: str = "") -> UsageSummary:
        """Get aggregated usage for a user in a period."""
        matching = [
            r
            for r in self._records
            if r.user_id == user_id
            and r.org_id == org_id
            and (not period or self._matches_period(r.timestamp, period))
        ]
        by_task: dict[str, int] = {}
        by_model: dict[str, int] = {}
        total_in = total_out = 0
        for r in matching:
            total_in += r.input_tokens
            total_out += r.output_tokens
            total_tokens = r.input_tokens + r.output_tokens
            by_task[r.task_type] = by_task.get(r.task_type, 0) + total_tokens
            by_model[r.model] = by_model.get(r.model, 0) + total_tokens
        return UsageSummary(
            user_id=user_id,
            org_id=org_id,
            period=period,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_requests=len(matching),
            by_task_type=by_task,
            by_model=by_model,
        )

    async def get_all_summaries(self, *, org_id: str, period: str = "") -> list[UsageSummary]:
        """Get aggregated usage for all users in an org. Admin-only."""
        user_ids = {r.user_id for r in self._records if r.org_id == org_id}
        summaries = []
        for uid in sorted(user_ids):
            summary = await self.get_summary(user_id=uid, org_id=org_id, period=period)
            summaries.append(summary)
        return summaries

    @staticmethod
    def _matches_period(timestamp: float, period: str) -> bool:
        dt = datetime.fromtimestamp(timestamp, tz=UTC)
        return dt.strftime("%Y-%m") == period
