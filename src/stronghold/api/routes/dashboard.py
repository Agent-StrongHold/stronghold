"""API route: dashboard — serves HTML pages for The Stronghold UI.

Dashboard pages require authentication (server-side check).
Login/logout/callback pages and static JS assets are public.
"""

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

_LOGIN_REDIRECT = HTMLResponse(status_code=302, headers={"Location": "/login"})

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

# -- Cost Aggregation API (public — no auth required for GET) --

@router.get("/v1/stronghold/costs")
async def get_costs(
    request: Request,
    group_by: str = "team",
    period: str = "weekly",
) -> dict:
    """Get cost aggregation data for the dashboard.

    Returns aggregated cost data grouped by team, user, or org.
    """
    container = getattr(getattr(request.app, "state", None), "container", None)
    if not container:
        return {"error": "Service unavailable"}

    # Get outcomes store
    outcomes_store = container.outcomes_store

    # Get quota tracker for budget info
    quota_tracker = container.quota_tracker

    # Aggregate costs based on group_by and period
    if group_by == "team":
        teams = outcomes_store.list_teams()
        result = {
            "teams": [
                {
                    "team_id": team.id,
                    "team_name": team.name,
                    "costs": _aggregate_team_costs(outcomes_store, quota_tracker, team.id, period),
                }
                for team in teams
            ]
        }
    elif group_by == "user":
        users = outcomes_store.list_users()
        result = {
            "users": [
                {
                    "user_id": user.id,
                    "user_name": user.name,
                    "costs": _aggregate_user_costs(outcomes_store, quota_tracker, user.id, period),
                }
                for user in users
            ]
        }
    elif group_by == "org":
        orgs = outcomes_store.list_orgs()
        result = {
            "orgs": [
                {
                    "org_id": org.id,
                    "org_name": org.name,
                    "costs": _aggregate_org_costs(outcomes_store, quota_tracker, org.id, period),
                }
                for org in orgs
            ]
        }
    else:
        return {"error": "Invalid group_by parameter"}

    return result

def _aggregate_team_costs(outcomes_store, quota_tracker, team_id: str, period: str) -> dict:
    """Aggregate costs by team."""
    # Get team outcomes
    outcomes = outcomes_store.get_team_outcomes(team_id)

    # Aggregate by model, provider, task_type
    by_model = {}
    by_provider = {}
    by_task_type = {}

    for outcome in outcomes:
        # Aggregate by model
        model_key = outcome.model
        by_model[model_key] = by_model.get(model_key, {"cost": 0.0, "count": 0})
        by_model[model_key]["cost"] += outcome.cost
        by_model[model_key]["count"] += 1

        # Aggregate by provider
        provider_key = outcome.provider
        by_provider[provider_key] = by_provider.get(provider_key, {"cost": 0.0, "count": 0})
        by_provider[provider_key]["cost"] += outcome.cost
        by_provider[provider_key]["count"] += 1

        # Aggregate by task_type
        task_type_key = outcome.task_type
        by_task_type[task_type_key] = by_task_type.get(task_type_key, {"cost": 0.0, "count": 0})
        by_task_type[task_type_key]["cost"] += outcome.cost
        by_task_type[task_type_key]["count"] += 1

    # Get trends
    daily_trend, weekly_trend = outcomes_store.get_team_cost_trends(team_id, period)

    # Get budget alerts
    alerts = []
    team_quota = quota_tracker.get_team_quota(team_id)
    if team_quota:
        current_spend = sum(outcome.cost for outcome in outcomes)
        if current_spend >= team_quota * 0.8:
            alerts.append({
                "type": "budget_threshold",
                "message": "Team has used 80% of monthly allocation",
                "current": current_spend,
                "quota": team_quota,
                "threshold": 0.8,
            })

    return {
        "by_model": [{"model": k, **v} for k, v in by_model.items()],
        "by_provider": [{"provider": k, **v} for k, v in by_provider.items()],
        "by_task_type": [{"task_type": k, **v} for k, v in by_task_type.items()],
        "trends": {
            "daily": [{"date": d["date"], "cost": d["cost"]} for d in daily_trend],
            "weekly": [{"week": w["week"], "cost": w["cost"]} for w in weekly_trend],
        },
        "alerts": alerts,
    }

def _aggregate_user_costs(outcomes_store, quota_tracker, user_id: str, period: str) -> dict:
    """Aggregate costs by user."""
    outcomes = outcomes_store.get_user_outcomes(user_id)

    by_model = {}
    by_provider = {}
    by_task_type = {}

    for outcome in outcomes:
        model_key = outcome.model
        by_model[model_key] = by_model.get(model_key, {"cost": 0.0, "count": 0})
        by_model[model_key]["cost"] += outcome.cost
        by_model[model_key]["count"] += 1

        provider_key = outcome.provider
        by_provider[provider_key] = by_provider.get(provider_key, {"cost": 0.0, "count": 0})
        by_provider[provider_key]["cost"] += outcome.cost
        by_provider[provider_key]["count"] += 1

        task_type_key = outcome.task_type
        by_task_type[task_type_key] = by_task_type.get(task_type_key, {"cost": 0.0, "count": 0})
        by_task_type[task_type_key]["cost"] += outcome.cost
        by_task_type[task_type_key]["count"] += 1

    daily_trend, weekly_trend = outcomes_store.get_user_cost_trends(user_id, period)

    return {
        "by_model": [{"model": k, **v} for k, v in by_model.items()],
        "by_provider": [{"provider": k, **v} for k, v in by_provider.items()],
        "by_task_type": [{"task_type": k, **v} for k, v in by_task_type.items()],
        "trends": {
            "daily": [{"date": d["date"], "cost": d["cost"]} for d in daily_trend],
            "weekly": [{"week": w["week"], "cost": w["cost"]} for w in weekly_trend],
        },
    }

def _aggregate_org_costs(outcomes_store, quota_tracker, org_id: str, period: str) -> dict:
    """Aggregate costs by org."""
    outcomes = outcomes_store.get_org_outcomes(org_id)

    by_model = {}
    by_provider = {}
    by_task_type = {}

    for outcome in outcomes:
        model_key = outcome.model
        by_model[model_key] = by_model.get(model_key, {"cost": 0.0, "count": 0})
        by_model[model_key]["cost"] += outcome.cost
        by_model[model_key]["count"] += 1

        provider_key = outcome.provider
        by_provider[provider_key] = by_provider.get(provider_key, {"cost": 0.0, "count": 0})
        by_provider[provider_key]["cost"] += outcome.cost
        by_provider[provider_key]["count"] += 1

        task_type_key = outcome.task_type
        by_task_type[task_type_key] = by_task_type.get(task_type_key, {"cost": 0.0, "count": 0})
        by_task_type[task_type_key]["cost"] += outcome.cost
        by_task_type[task_type_key]["count"] += 1

    daily_trend, weekly_trend = outcomes_store.get_org_cost_trends(org_id, period)

    return {
        "by_model": [{"model": k, **v} for k, v in by_model.items()],
        "by_provider": [{"provider": k, **v} for k, v in by_provider.items()],
        "by_task_type": [{"task_type": k, **v} for k, v in by_task_type.items()],
        "trends": {
            "daily": [{"date": d["date"], "cost": d["cost"]} for d in daily_trend],
            "weekly": [{"week": w["week"], "cost": w["cost"]} for w in weekly_trend],
        },
    }

# -- Login & Auth (public — no auth required) --

@router.get("/logout")
async def logout_redirect() -> HTMLResponse:
    """Logout — full nuclear option.

    Returns a page that:
    1. Server Set-Cookie headers delete HttpOnly cookies
    2. Client JS deletes everything JS can reach
    3. Client JS waits 500ms for cookies to clear
    4. Only THEN redirects to login page
    """
    html = (
        "<!DOCTYPE html><html><head>"
        "<title>Logging out...</title></head>\n"
        '<body style="background:#1a1a2e;color:#d4d0c8;'
        "font-family:monospace;display:flex;align-items:center;"
        'justify-content:center;height:100vh;margin:0">'
        """
<div style="text-align:center">
<div style="font-size:3rem;margin-bottom:16px">&#x1F3F0;</div>
<div>Logging out of the fortress...</div>
</div>
<script>
localStorage.clear();
sessionStorage.clear();
document.cookie.split(';').forEach(function(c){
  var n=c.split('=')[0].trim();
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 0Id="sidebar-overlay" class="sidebar-overlay"></div>\n<script>\nfunction closeSidebar() { document.getElementById(\\'sidebar\\').classList.remove(\\'open\\'); document.getElementById(\\'sidebar-overlay\\').classList.remove(\\'open\\'); }\n</script>\n</body>\n</html>\n"
    )

    response = HTMLResponse(content=html)
    # Server-side: delete HttpOnly cookies that JS can't reach
    for name in (
        "stronghold_session",
        "stronghold_logged_in",
        "sh_session_v2",
        "sh_logged_in_v2",
        "sh_session",
        "sh_logged_in",
    ):
        response.delete_cookie(key=name, path="/")
        response.delete_cookie(key=name, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(key=name, path="/", secure=True, samesite="lax")
    return response

@router.get("/login")
async def login_page() -> HTMLResponse:
    """The Gates — login page."""
    return _serve_page("login.html")

@router.get("/login/callback")
async def login_callback() -> HTMLResponse:
    """OIDC callback — login page JS handles the code exchange."""
    return _serve_page("login.html")

_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}

def _serve_js(filename: str) -> Response:
    """Serve a JS file with no-cache headers."""
    for d in _DASHBOARD_CANDIDATES:
        filepath = d / filename
        if filepath.exists():
            return Response(
                content=filepath.read_text(encoding="utf-8"),
                media_type="application/javascript",
                headers=_NO_CACHE,
            )
    return Response(content=f"// {filename} not found", media_type="application/javascript")

@router.get("/dashboard/auth.js")
async def auth_js() -> Response:
    return _serve_js("auth.js")

@router.get("/dashboard/scan-report.js")
async def scan_report_js() -> Response:
    return _serve_js("scan-report.js")

@router.get("/dashboard/outcomes")
async def outcomes_dashboard(request: Request) -> HTMLResponse:
    """The Treasury — outcomes and analytics dashboard."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("outcomes.html")

@router.get("/v1/stronghold/costs/export")
async def export_costs(
    request: Request,
    group_by: str = "team",
    period: str = "weekly",
    format: str = "json",
) -> Response:
    """Export cost aggregation data as CSV.

    Returns aggregated cost data grouped by team, user, or org.
    """
    container = getattr(getattr(request.app, "state", None), "container", None)
    if not container:
        return Response(content="Service unavailable", status_code=503)

    outcomes_store = container.outcomes_store
    quota_tracker = container.quota_tracker

    if group_by == "team":
        teams = outcomes_store.list_teams()
        rows = []
        for team in teams:
            costs = _aggregate_team_costs(outcomes_store, quota_tracker, team.id, period)
            for model in costs["by_model"]:
                rows.append({
                    "team_id": team.id,
                    "team_name": team.name,
                    "user": None,
                    "model": model["model"],
                    "provider": None,
                    "task_type": None,
                    "cost": model["cost"],
                    "count": model["count"],
                })
            for provider in costs["by_provider"]:
                rows.append({
                    "team_id": team.id,
                    "team_name": team.name,
                    "user": None,
                    "model": None,
                    "provider": provider["provider"],
                    "task_type": None,
                    "cost": provider["cost"],
                    "count": provider["count"],
                })
            for task_type in costs["by_task_type"]:
                rows.append({
                    "team_id": team.id,
                    "team_name": team.name,
                    "user": None,
                    "model": None,
                    "provider": None,
                    "task_type": task_type["task_type"],
                    "cost": task_type["cost"],
                    "count": task_type["count"],
                })
    elif group_by == "user":
        users = outcomes_store.list_users()
        rows = []
        for user in users:
            costs = _aggregate_user_costs(outcomes_store, quota_tracker, user.id, period)
            for model in costs["by_model"]:
                rows.append({
                    "user_id": user.id,
                    "user_name": user.name,
                    "team_id": None,
                    "team_name": None,
                    "model": model["model"],
                    "provider": None,
                    "task_type": None,
                    "cost": model["cost"],
                    "count": model["count"],
                })
            for provider in costs["by_provider"]:
                rows.append({
                    "user_id": user.id,
                    "user_name": user.name,
                    "team_id": None,
                    "team_name": None,
                    "model": None,
                    "provider": provider["provider"],
                    "task_type": None,
                    "cost": provider["cost"],
                    "count": provider["count"],
                })
            for task_type in costs["by_task_type"]:
                rows.append({
                    "user_id": user.id,
                    "user_name": user.name,
                    "team_id": None,
                    "team_name": None,
                    "model": None,
                    "provider": None,
                    "task_type": task_type["task_type"],
                    "cost": task_type["cost"],
                    "count": task_type["count"],
                })
    elif group_by == "org":
        orgs = outcomes_store.list_orgs()
        rows = []
        for org in orgs:
            costs = _aggregate_org_costs(outcomes_store, quota_tracker, org.id, period)
            for model in costs["by_model"]:
                rows.append({
                    "org_id": org.id,
                    "org_name": org.name,
                    "team_id": None,
                    "team_name": None,
                    "user_id": None,
                    "user_name": None,
                    "model": model["model"],
                    "provider": None,
                    "task_type": None,
                    "cost": model["cost"],
                    "count": model["count"],
                })
            for provider in costs["by_provider"]:
                rows.append({
                    "org_id": org.id,
                    "org_name": org.name,
                    "team_id": None,
                    "team_name": None,
                    "user_id": None,
                    "user_name": None,
                    "model": None,
                    "provider": provider["provider"],
                    "task_type": None,
                    "cost": provider["cost"],
                    "count": provider["count"],
                })
            for task_type in costs["by_task_type"]:
                rows.append({
                    "org_id": org.id,
                    "org_name": org.name,
                    "team_id": None,
                    "team_name": None,
                    "user_id": None,
                    "user_name": None,
                    "model": None,
                    "provider": None,
                    "task_type": task_type["task_type"],
                    "cost": task_type["cost"],
                    "count": task_type["count"],
                })
    else:
        return Response(content="Invalid group_by parameter", status_code=400)

    if format == "csv":
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=["team_id", "team_name", "user_id", "user_name", "org_id", "org_name", "model", "provider", "task_type", "cost", "count"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        csv_content = output.getvalue()
        return Response(
            content=csv_content,
            media_type="text/csv; charset=utf-8",
        )
    else:
        return Response(content='{"error": "Only CSV format supported"}', status_code=400)