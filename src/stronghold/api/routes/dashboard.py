"""API route: dashboard — serves Agent Turing's field console.

Five surfaces (auth required): Chat, Notebook, Blog, Profile, Memory.
Login/logout/callback pages and static assets (CSS/JSX/SVG) are public.
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

# CSP tuned for the Phosphor-Noir design bundle:
# - unpkg.com for React 18 + Babel standalone (integrity-hashed in HTML)
# - 'unsafe-eval' for Babel's in-browser JSX transform
# - Google Fonts for VT323 + IBM Plex families
_CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "connect-src 'self'",
        "img-src 'self' data:",
    ]
)

_LOGIN_REDIRECT = HTMLResponse(status_code=302, headers={"Location": "/login"})


def _find_path(relative: str) -> Path | None:
    """Locate a file relative to the dashboard directory across deploy layouts."""
    for d in _DASHBOARD_CANDIDATES:
        candidate = d / relative
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _serve_page(filename: str) -> HTMLResponse:
    """Serve an HTML dashboard page with no-cache and CSP headers."""
    path = _find_path(filename)
    if path is None:
        return HTMLResponse(
            content=f"<h1>Page not found: {filename}</h1>",
            status_code=404,
        )
    return HTMLResponse(
        content=path.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Security-Policy": _CSP,
        },
    )


async def _check_auth(request: Request) -> bool:
    """Server-side auth check for dashboard pages.

    Returns True if authenticated (valid auth header or session cookie).
    """
    container = getattr(getattr(request.app, "state", None), "container", None)
    if not container:
        return False

    auth_header = request.headers.get("authorization")
    if auth_header:
        try:
            await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
            return True
        except ValueError:
            pass

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


# ── Turing field-console surfaces (auth required) ──


@router.get("/dashboard")
async def dashboard_hub(request: Request) -> HTMLResponse:
    """The hub — lists the five surfaces."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("index.html")


@router.get("/dashboard/chat")
async def chat_surface(request: Request) -> HTMLResponse:
    """Chat — handler ↔ AT-01 wire."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("chat.html")


@router.get("/dashboard/notebook")
async def notebook_surface(request: Request) -> HTMLResponse:
    """Notebook — themed Obsidian vault (working memory)."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("notebook.html")


@router.get("/dashboard/blog")
async def blog_surface(request: Request) -> HTMLResponse:
    """Blog — handler-POV preview of Turing's WordPress field dossier."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("blog.html")


@router.get("/dashboard/profile")
async def profile_surface(request: Request) -> HTMLResponse:
    """Profile — asset dossier."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("profile.html")


@router.get("/dashboard/memory")
async def memory_surface(request: Request) -> HTMLResponse:
    """Memory — raw 7-tier DB inspector (CRUD)."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("memory.html")


@router.get("/dashboard/canvas")
async def canvas_surface(request: Request) -> HTMLResponse:
    """Design canvas — all five surfaces side-by-side for review."""
    if not await _check_auth(request):
        return _LOGIN_REDIRECT
    return _serve_page("canvas.html")


# ── Login & Auth (public — no auth required) ──


@router.get("/logout")
async def logout_redirect() -> HTMLResponse:
    """Logout — clear session cookies and client-side storage, then redirect to /."""
    html = (
        "<!DOCTYPE html><html><head>"
        "<title>Disconnecting...</title></head>\n"
        '<body style="background:#0A0B0A;color:#ECEAE3;'
        "font-family:'IBM Plex Mono',monospace;display:flex;align-items:center;"
        'justify-content:center;height:100vh;margin:0">'
        '<div style="text-align:center">'
        '<div style="font-size:2rem;margin-bottom:16px;color:#5EE88C;'
        'text-shadow:0 0 10px rgba(94,232,140,0.5)">'
        "&#x25C6; WIRE &middot; SEVERED</div>"
        '<div style="font-size:11px;letter-spacing:0.24em;'
        'text-transform:uppercase;color:#8F9692">'
        "Disconnecting handler session</div>"
        "</div>"
        + """
<script>
localStorage.clear();
sessionStorage.clear();
document.cookie.split(';').forEach(function(c){
  var n=c.split('=')[0].trim();
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;secure';
  document.cookie=n+'=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;secure;samesite=lax';
});
setTimeout(function(){location.href='/';},500);
</script>
</body></html>"""
    )

    response = HTMLResponse(content=html)
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
    """Login page."""
    return _serve_page("login.html")


@router.get("/login/callback")
async def login_callback() -> HTMLResponse:
    """OIDC callback — login page JS handles the code exchange."""
    return _serve_page("login.html")


# ── Static assets (public — referenced from HTML pages) ──


_NO_CACHE = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _serve_static(relative: str, media_type: str) -> Response:
    """Serve a static asset with no-cache headers."""
    path = _find_path(relative)
    if path is None:
        return Response(
            content=f"// {relative} not found",
            media_type=media_type,
            status_code=404,
        )
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type=media_type,
        headers=_NO_CACHE,
    )


def _safe_name(name: str) -> bool:
    """Reject any path traversal attempts in static asset names."""
    return (
        bool(name)
        and "/" not in name
        and "\\" not in name
        and not name.startswith(".")
        and ".." not in name
    )


@router.get("/dashboard/auth.js")
async def auth_js() -> Response:
    return _serve_static("auth.js", "application/javascript")


@router.get("/dashboard/styles/{filename}")
async def dashboard_style(filename: str) -> Response:
    if not _safe_name(filename) or not filename.endswith(".css"):
        return Response(content="", status_code=404)
    return _serve_static(f"styles/{filename}", "text/css")


@router.get("/dashboard/components/{filename}")
async def dashboard_component(filename: str) -> Response:
    if not _safe_name(filename) or not filename.endswith(".jsx"):
        return Response(content="", status_code=404)
    return _serve_static(f"components/{filename}", "text/babel")


@router.get("/dashboard/assets/{filename}")
async def dashboard_asset(filename: str) -> Response:
    if not _safe_name(filename):
        return Response(content="", status_code=404)
    ext = filename.rsplit(".", 1)[-1].lower()
    media = {
        "svg": "image/svg+xml",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext)
    if media is None:
        return Response(content="", status_code=404)
    path = _find_path(f"assets/{filename}")
    if path is None:
        return Response(content="", status_code=404)
    return Response(
        content=path.read_bytes(),
        media_type=media,
        headers=_NO_CACHE,
    )
