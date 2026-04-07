from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

router = APIRouter()

_DASHBOARD_CANDIDATES = [
    Path(__file__).parent.parent.parent / "dashboard",
    Path("/app/src/stronghold/dashboard"),
    Path("src/stronghold/dashboard"),
]

_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self'",
        "img-src 'self' data:",
    ]
)

_LOGIN_REDIRECT = HTMLResponse(status_code=322, headers={"Location": "/login"})


def _serve_page(filename: str) -> HTMLResponse:
    """Serve an HTML dashboard page with no-cache and CSP headers."""
    for d in _DASHBOARD_CANDIDATES:
        filepath = d / filename
        if filepath.exists():
            return HTMLResponse(
                content=filepath.read_text(encoding="utf-8"),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Content-Security-Policy": _CSP,
                },
            )
    return HTMLResponse(
        content=f"<h1>Page not found: {filename}</h1>",
        status_code=404,
    )


async def _check_auth(request: Request) -> bool:
    """Server-side auth check for dashboard pages.

    Returns True if authenticated (valid auth header or session cookie).
    Returns False if no valid credentials found.
    """
    container = getattr(getattr(request.app, "state", None), "container", None)
    if not container:
        return False  # No container yet (startup) — deny access until ready

    # Check auth header
    auth_header = request.headers.get("authorization")
    if auth_header:
        try:
            await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
            return True
        except ValueError:
            pass

    # Check session cookie — must actually validate the token, not just check existence
    cookie_name = container.config.auth.session_cookie_name
    cookie_value = request.cookies.get(cookie_name)
    if not cookie_value:
        return False
    try:
        await container.auth_provider.authenticate(
            f"Bearer {cookie_value}",
            headers=dict(request.headers),
        )
        return True
    except ValueError:
        return False


@router.get("/dashboard/skills")
async def skills_dashboard(request: Request) -> HTMLResponse:
    """The Armory — skill management dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("skills.html")


@router.get("/dashboard/security")
async def security_dashboard(request: Request) -> HTMLResponse:
    """The Watchtower — security dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("security.html")


@router.get("/dashboard/outcomes")
async def outcomes_dashboard(request: Request) -> HTMLResponse:
    """The Treasury — outcomes and analytics dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("outcomes.html")


@router.get("/dashboard/agents")
async def agents_dashboard(request: Request) -> HTMLResponse:
    """The Knights — agent roster dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("agents.html")


@router.get("/dashboard/mcp")
async def mcp_dashboard(request: Request) -> HTMLResponse:
    """The Forge — MCP server management dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("mcp.html")


@router.get("/dashboard/quota")
async def quota_dashboard(request: Request) -> HTMLResponse:
    """The Ledger — provider quota and budget dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("quota.html")


@router.get("/dashboard/profile")
async def profile_dashboard(request: Request) -> HTMLResponse:
    """Profile — user identity and preferences."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("profile.html")


@router.get("/dashboard/leaderboard")
async def leaderboard_dashboard(request: Request) -> HTMLResponse:
    """The Arena — leaderboard and rankings."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("leaderboard.html")


@router.get("/dashboard/team")
async def team_dashboard(request: Request) -> HTMLResponse:
    """The Barracks — team administration dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("team.html")


@router.get("/dashboard/dungeon")
async def dungeon_dashboard(request: Request) -> HTMLResponse:
    """The Dungeon — strikes, violations, and appeals management."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("dungeon.html")


@router.get("/dashboard/mason")
async def mason_dashboard(request: Request) -> HTMLResponse:
    """The Workshop — Mason autonomous agent management (admin)."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("mason.html")


@router.get("/dashboard/org")
async def org_dashboard(request: Request) -> HTMLResponse:
    """The Throne Room — organization administration dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("org.html")


@router.get("/v1/stronghold/outcomes")
async def outcomes_api(
    request: Request,
    group_by: str = "team",
    period: str = "weekly",
    format: str = "json",
    include_suggestions: str = "false",
) -> Response:
    """API endpoint for cost aggregation dashboard data."""
    container = getattr(getattr(request.app, "state", None), "container", None)
    if not container:
        return Response(status_code=500, content="Container not available")

    # Authenticate
    auth_header = request.headers.get("authorization")
    if not auth_header:
        return Response(status_code=401, content="Unauthorized")

    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError:
        return Response(status_code=403, content="Forbidden")

    # Validate parameters
    valid_group_by = ["team", "user", "org"]
    valid_period = ["daily", "weekly", "monthly"]
    valid_format = ["json", "csv"]

    if group_by not in valid_group_by:
        return Response(
            status_code=422,
            content="Invalid group_by parameter. Must be one of: team, user, org",
        )
    if period not in valid_period:
        return Response(
            status_code=422,
            content="Invalid period parameter. Must be one of: daily, weekly, monthly",
        )
    if format not in valid_format:
        return Response(
            status_code=422,
            content="Invalid format parameter. Must be one of: json, csv",
        )

    # Get cost data from stores
    outcome_store = container.outcome_store

    # Get outcomes based on period
    outcomes = []
    if period == "daily":
        outcomes = outcome_store.get_daily_outcomes()
    elif period == "weekly":
        outcomes = outcome_store.get_weekly_outcomes()
    elif period == "monthly":
        outcomes = outcome_store.get_monthly_outcomes()

    # Group by the requested dimension
    grouped_data = (
        {"teams": []}
        if group_by == "team"
        else {"users": []}
        if group_by == "user"
        else {"orgs": []}
    )

    for outcome in outcomes:
        if group_by == "team":
            team_id = outcome.team_id
            user_id = outcome.user_id
            model = outcome.model
            provider = outcome.provider
            task_type = outcome.task_type
            cost = outcome.cost

            # Find or create team entry
            team_entry = next((t for t in grouped_data["teams"] if t["team_id"] == team_id), None)
            if not team_entry:
                team_entry = {
                    "team_id": team_id,
                    "budget": container.quota_tracker.get_team_budget(team_id),
                    "costs": {
                        "by_model": [],
                        "by_provider": [],
                        "by_task_type": [],
                        "trends": {"daily": [], "weekly": []},
                        "total_spend": 0.0,
                        "alerts": [],
                    },
                }
                grouped_data["teams"].append(team_entry)

            # Update team costs
            team_entry["costs"]["total_spend"] += cost

            # Update breakdowns
            self._update_breakdown(team_entry["costs"]["by_model"], {"model": model, "cost": cost})
            self._update_breakdown(
                team_entry["costs"]["by_provider"], {"provider": provider, "cost": cost}
            )
            self._update_breakdown(
                team_entry["costs"]["by_task_type"], {"task_type": task_type, "cost": cost}
            )

            # Update trends
            self._update_trends(team_entry["costs"]["trends"], outcome.timestamp, cost, period)

            # Check budget alerts
            self._check_budget_alerts(team_entry)

        elif group_by == "user":
            user_id = outcome.user_id
            model = outcome.model
            provider = outcome.provider
            task_type = outcome.task_type
            cost = outcome.cost

            user_entry = next((u for u in grouped_data["users"] if u["user_id"] == user_id), None)
            if not user_entry:
                user_entry = {
                    "user_id": user_id,
                    "costs": {
                        "by_model": [],
                        "by_provider": [],
                        "by_task_type": [],
                        "trends": {"daily": [], "weekly": []},
                        "total_spend": 0.0,
                        "alerts": [],
                    },
                }
                grouped_data["users"].append(user_entry)

            user_entry["costs"]["total_spend"] += cost
            self._update_breakdown(user_entry["costs"]["by_model"], {"model": model, "cost": cost})
            self._update_breakdown(
                user_entry["costs"]["by_provider"], {"provider": provider, "cost": cost}
            )
            self._update_breakdown(
                user_entry["costs"]["by_task_type"], {"task_type": task_type, "cost": cost}
            )
            self._update_trends(user_entry["costs"]["trends"], outcome.timestamp, cost, period)

        elif group_by == "org":
            org_id = outcome.org_id
            model = outcome.model
            provider = outcome.provider
            task_type = outcome.task_type
            cost = outcome.cost

            org_entry = next((o for o in grouped_data["orgs"] if o["org_id"] == org_id), None)
            if not org_entry:
                org_entry = {
                    "org_id": org_id,
                    "budget": container.quota_tracker.get_org_budget(org_id),
                    "costs": {
                        "by_model": [],
                        "by_provider": [],
                        "by_task_type": [],
                        "trends": {"daily": [], "weekly": []},
                        "total_spend": 0.0,
                        "alerts": [],
                    },
                }
                grouped_data["orgs"].append(org_entry)

            org_entry["costs"]["total_spend"] += cost
            self._update_breakdown(org_entry["costs"]["by_model"], {"model": model, "cost": cost})
            self._update_breakdown(
                org_entry["costs"]["by_provider"], {"provider": provider, "cost": cost}
            )
            self._update_breakdown(
                org_entry["costs"]["by_task_type"], {"task_type": task_type, "cost": cost}
            )
            self._update_trends(org_entry["costs"]["trends"], outcome.timestamp, cost, period)
            self._check_budget_alerts(org_entry)

    # Add optimization suggestions if requested
    if include_suggestions.lower() == "true":
        for entry in (
            grouped_data.get("teams", [])
            + grouped_data.get("users", [])
            + grouped_data.get("orgs", [])
        ):
            entry["costs"]["optimization_suggestions"] = self._generate_optimization_suggestions(
                entry["costs"]
            )

    # Return appropriate format
    if format == "csv":
        csv_data = self._convert_to_csv(grouped_data, group_by)
        return Response(
            content=csv_data,
            media_type="text/csv; charset=utf-8",
        )
    else:
        return Response(
            content=grouped_data,
            media_type="application/json",
        )


def _update_breakdown(self, breakdown_list: list, item: dict) -> None:
    """Update breakdown list with new item."""
    existing = next((b for b in breakdown_list if b["model"] == item["model"]), None)
    if existing:
        existing["cost"] += item["cost"]
        existing["count"] = existing.get("count", 0) + 1
    else:
        breakdown_list.append({"model": item["model"], "cost": item["cost"], "count": 1})


def _update_trends(self, trends: dict, timestamp: str, cost: float, period: str) -> None:
    """Update trends data."""
    import datetime

    date_obj = datetime.datetime.fromisoformat(timestamp)

    # Daily trends
    daily_key = date_obj.strftime("%Y-%m-%d")
    daily_entry = next((d for d in trends["daily"] if d["date"] == daily_key), None)
    if daily_entry:
        daily_entry["cost"] += cost
    else:
        trends["daily"].append({"date": daily_key, "cost": cost})

    # Weekly trends
    weekly_key = f"{date_obj.year}-W{date_obj.isocalendar()[1]}"
    weekly_entry = next((w for w in trends["weekly"] if w["week"] == weekly_key), None)
    if weekly_entry:
        weekly_entry["cost"] += cost
    else:
        trends["weekly"].append({"week": weekly_key, "cost": cost})


def _check_budget_alerts(self, entry: dict) -> None:
    """Check budget thresholds and add alerts if needed."""
    budget = entry.get("budget", 1000.0)
    total_spend = entry["costs"]["total_spend"]

    alerts = entry["costs"].setdefault("alerts", [])

    if total_spend >= 0.8 * budget:
        alerts.append(
            {
                "type": "budget_threshold",
                "threshold": 80,
                "message": "Team has used 80% of monthly allocation",
            }
        )

    if total_spend >= budget:
        alerts.append(
            {
                "type": "budget_threshold",
                "threshold": 100,
                "message": "Team has used 100% of monthly allocation",
            }
        )


def _generate_optimization_suggestions(self, costs: dict) -> list:
    """Generate cost optimization suggestions."""
    suggestions = []

    # Model switching suggestions
    by_model = costs.get("by_model", [])
    if len(by_model) > 1:
        # Sort by cost descending
        sorted_models = sorted(by_model, key=lambda x: x["cost"], reverse=True)
        expensive_model = sorted_models[0]
        affordable_models = sorted_models[1:]

        for affordable in affordable_models:
            if affordable["cost"] > 0:
                savings = expensive_model["cost"] - affordable["cost"]
                if savings > 0:
                    suggestions.append(
                        {
                            "type": "model_switching",
                            "model": expensive_model["model"],
                            "recommended_model": affordable["model"],
                            "estimated_savings": savings,
                            "quality_impact": "neutral",
                            "task_types": [t["task_type"] for t in costs.get("by_task_type", [])],
                        }
                    )

    # Model comparison suggestions
    by_task_type = costs.get("by_task_type", [])
    for task in by_task_type:
        task_type = task["task_type"]
        models_for_task = [m for m in by_model if m["cost"] > 0]
        if len(models_for_task) > 1:
            # Simple comparison - find cheapest model for this task type
            cheapest = min(models_for_task, key=lambda x: x["cost"])
            if cheapest["cost"] < sum(m["cost"] for m in models_for_task) / len(models_for_task):
                suggestions.append(
                    {
                        "type": "model_comparison",
                        "task_type": task_type,
                        "current_model": next(
                            m["model"]
                            for m in models_for_task
                            if m["cost"] == max(m["cost"] for m in models_for_task)
                        ),
                        "recommended_model": cheapest["model"],
                        "estimated_savings": sum(m["cost"] for m in models_for_task)
                        - cheapest["cost"],
                        "quality_impact": "improved",
                    }
                )

    return suggestions


def _convert_to_csv(self, data: dict, group_by: str) -> str:
    """Convert grouped data to CSV format."""
    import csv
    from io import StringIO

    output = StringIO()
    writer = csv.writer(output)

    # Write headers
    if group_by == "team":
        writer.writerow(["team_id", "user", "model", "provider", "task_type", "cost", "timestamp"])
    elif group_by == "user":
        writer.writerow(["user_id", "team", "model", "provider", "task_type", "cost", "timestamp"])
    elif group_by == "org":
        writer.writerow(["org_id", "team", "model", "provider", "task_type", "cost", "timestamp"])

    # Write data rows
    if group_by == "team":
        for team in data.get("teams", []):
            for model_breakdown in team["costs"]["by_model"]:
                for _ in range(model_breakdown.get("count", 1)):
                    writer.writerow(
                        [
                            team["team_id"],
                            "",  # user placeholder
                            model_breakdown["model"],
                            "",  # provider placeholder
                            "",  # task_type placeholder
                            str(model_breakdown["cost"]),
                            "",  # timestamp placeholder
                        ]
                    )
    elif group_by == "user":
        for user in data.get("users", []):
            for model_breakdown in user["costs"]["by_model"]:
                for _ in range(model_breakdown.get("count", 1)):
                    writer.writerow(
                        [
                            user["user_id"],
                            "",  # team placeholder
                            model_breakdown["model"],
                            "",  # provider placeholder
                            "",  # task_type placeholder
                            str(model_breakdown["cost"]),
                            "",  # timestamp placeholder
                        ]
                    )
    elif group_by == "org":
        for org in data.get("orgs", []):
            for model_breakdown in org["costs"]["by_model"]:
                for _ in range(model_breakdown.get("count", 1)):
                    writer.writerow(
                        [
                            org["org_id"],
                            "",  # team placeholder
                            model_breakdown["model"],
                            "",  # provider placeholder
                            "",  # task_type placeholder
                            str(model_breakdown["cost"]),
                            "",  # timestamp placeholder
                        ]
                    )

    return output.getvalue()
