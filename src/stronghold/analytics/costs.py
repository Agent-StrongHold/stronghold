"""Cost analytics and chargeback reporting."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class CostRecord:
    """A single cost record for analytics tracking."""

    user_id: str = ""
    org_id: str = ""
    team_id: str = ""
    model: str = ""
    provider: str = ""
    task_type: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: float = 0.0


@dataclass
class CostSummary:
    """Aggregated cost summary for a given period and org."""

    period: str = ""
    org_id: str = ""
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_requests: int = 0
    by_user: dict[str, float] = field(default_factory=dict)
    by_team: dict[str, float] = field(default_factory=dict)
    by_model: dict[str, float] = field(default_factory=dict)
    by_task_type: dict[str, float] = field(default_factory=dict)


def _period_key(timestamp: float) -> str:
    """Extract YYYY-MM period key from a unix timestamp."""
    if timestamp <= 0:
        return ""
    dt = datetime.fromtimestamp(timestamp, tz=UTC)
    return f"{dt.year}-{dt.month:02d}"


class InMemoryCostTracker:
    """In-memory cost tracker for testing and local dev."""

    def __init__(self) -> None:
        self._records: list[CostRecord] = []

    async def record(self, record: CostRecord) -> None:
        """Store a cost record."""
        self._records.append(record)

    def _filter(self, *, org_id: str, period: str = "") -> list[CostRecord]:
        """Filter records by org_id and optional period."""
        result: list[CostRecord] = []
        for r in self._records:
            if r.org_id != org_id:
                continue
            if period and _period_key(r.timestamp) != period:
                continue
            result.append(r)
        return result

    async def get_summary(
        self, *, org_id: str, period: str = "", group_by: str = "user"
    ) -> CostSummary:
        """Build a cost summary for the given org and optional period.

        The group_by parameter is accepted for API compatibility but all
        breakdown dicts (by_user, by_team, by_model, by_task_type) are
        always populated.
        """
        records = self._filter(org_id=org_id, period=period)

        total_cost = 0.0
        total_tokens = 0
        by_user: dict[str, float] = defaultdict(float)
        by_team: dict[str, float] = defaultdict(float)
        by_model: dict[str, float] = defaultdict(float)
        by_task_type: dict[str, float] = defaultdict(float)

        for r in records:
            total_cost += r.cost_usd
            total_tokens += r.input_tokens + r.output_tokens
            if r.user_id:
                by_user[r.user_id] += r.cost_usd
            if r.team_id:
                by_team[r.team_id] += r.cost_usd
            if r.model:
                by_model[r.model] += r.cost_usd
            if r.task_type:
                by_task_type[r.task_type] += r.cost_usd

        return CostSummary(
            period=period,
            org_id=org_id,
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            total_requests=len(records),
            by_user=dict(by_user),
            by_team=dict(by_team),
            by_model=dict(by_model),
            by_task_type=dict(by_task_type),
        )

    async def export_csv(self, *, org_id: str, period: str = "") -> str:
        """Export cost records as CSV string."""
        records = self._filter(org_id=org_id, period=period)
        output = io.StringIO()
        fieldnames = [
            "user_id",
            "org_id",
            "team_id",
            "model",
            "provider",
            "task_type",
            "input_tokens",
            "output_tokens",
            "cost_usd",
            "timestamp",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "user_id": r.user_id,
                    "org_id": r.org_id,
                    "team_id": r.team_id,
                    "model": r.model,
                    "provider": r.provider,
                    "task_type": r.task_type,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "cost_usd": r.cost_usd,
                    "timestamp": r.timestamp,
                }
            )
        return output.getvalue()

    async def get_optimization_suggestions(self, *, org_id: str) -> list[dict[str, Any]]:
        """Suggest cost optimizations based on usage patterns.

        Returns a list of suggestion dicts with keys:
            type: str  — suggestion category (cheaper_model, high_spend_task)
            message: str — human-readable explanation
        """
        records = self._filter(org_id=org_id)
        if not records:
            return []

        suggestions: list[dict[str, Any]] = []

        # ── Suggestion 1: cheaper model available for same task type ──
        # Group (task_type, model) → avg cost per request
        task_model_costs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for r in records:
            if r.task_type and r.model:
                task_model_costs[r.task_type][r.model].append(r.cost_usd)

        for task_type, model_costs in task_model_costs.items():
            if len(model_costs) < 2:
                continue
            avg_costs: dict[str, float] = {}
            for model, costs in model_costs.items():
                avg_costs[model] = sum(costs) / len(costs)
            most_expensive = max(avg_costs, key=lambda m: avg_costs[m])
            cheapest = min(avg_costs, key=lambda m: avg_costs[m])
            if most_expensive == cheapest:
                continue
            ratio = avg_costs[most_expensive] / max(avg_costs[cheapest], 1e-9)
            if ratio >= 2.0:
                suggestions.append(
                    {
                        "type": "cheaper_model",
                        "message": (
                            f"Model {most_expensive} is {ratio:.0f}x more expensive "
                            f"than {cheapest} for '{task_type}' tasks with similar "
                            f"token counts. Consider using {cheapest} for simple "
                            f"'{task_type}' requests."
                        ),
                    }
                )

        # ── Suggestion 2: high-spend task type ──
        total_cost = sum(r.cost_usd for r in records)
        if total_cost > 0:
            task_costs: dict[str, float] = defaultdict(float)
            for r in records:
                if r.task_type:
                    task_costs[r.task_type] += r.cost_usd
            for task_type, cost in task_costs.items():
                pct = cost / total_cost
                if pct >= 0.5:
                    suggestions.append(
                        {
                            "type": "high_spend_task",
                            "message": (
                                f"Task type '{task_type}' accounts for "
                                f"{pct:.0%} of total spend "
                                f"(${cost:.2f} of ${total_cost:.2f}). "
                                f"Consider caching repeated queries or "
                                f"reviewing usage patterns."
                            ),
                        }
                    )

        return suggestions
