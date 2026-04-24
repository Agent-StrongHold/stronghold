"""Tests for dashboard routes (dashboard.py).

The Turing field console has five auth-gated surfaces served from
``src/stronghold/dashboard/``: Chat, Notebook, Blog, Profile, Memory —
plus a hub (``/dashboard``) and a design canvas (``/dashboard/canvas``).

Each route is verified twice:
1. Unauthenticated: 302 redirect to /login.
2. Authenticated: the real HTML from disk, with CSP + no-cache headers.

Login-related pages and static assets are public and asserted separately.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.dashboard import router as dashboard_router

_DASHBOARD_DIR = Path(__file__).resolve().parents[2] / "src" / "stronghold" / "dashboard"


class _AlwaysAllowAuthProvider:
    """Stub auth provider that accepts any non-empty Bearer token."""

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,
    ) -> object:
        if not authorization:
            msg = "missing auth"
            raise ValueError(msg)
        return object()


class _FakeConfig:
    class _Auth:
        session_cookie_name = "stronghold_session"

    auth = _Auth()


class _FakeContainer:
    config = _FakeConfig()
    auth_provider = _AlwaysAllowAuthProvider()


@pytest.fixture
def dashboard_app() -> FastAPI:
    """App with just the dashboard router. No container attached —
    every auth-gated route should redirect to /login."""
    app = FastAPI()
    app.include_router(dashboard_router)
    return app


@pytest.fixture
def authed_dashboard_app(dashboard_app: FastAPI) -> FastAPI:
    """Same router, with a container whose auth provider always accepts."""
    dashboard_app.state.container = _FakeContainer()
    return dashboard_app


def _assert_redirects_to_login(resp) -> None:  # type: ignore[no-untyped-def]
    assert resp.status_code == 302, (
        f"unauthenticated dashboard should redirect, got {resp.status_code}"
    )
    assert resp.headers["location"] == "/login"


def _assert_serves_dashboard_page(resp, filename: str) -> None:  # type: ignore[no-untyped-def]
    """Assert the route served the exact file from the dashboard dir."""
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert f"Page not found: {filename}" not in body
    on_disk = (_DASHBOARD_DIR / filename).read_text(encoding="utf-8")
    assert body == on_disk
    assert "default-src 'self'" in resp.headers.get("content-security-policy", "")
    assert "no-cache" in resp.headers.get("cache-control", "")


# Every auth-gated surface: (url, filename).
_SURFACES = [
    ("/dashboard", "index.html"),
    ("/dashboard/chat", "chat.html"),
    ("/dashboard/notebook", "notebook.html"),
    ("/dashboard/blog", "blog.html"),
    ("/dashboard/profile", "profile.html"),
    ("/dashboard/memory", "memory.html"),
    ("/dashboard/canvas", "canvas.html"),
]


@pytest.mark.parametrize(("path", "_filename"), _SURFACES)
class TestSurfaceAuthGate:
    def test_redirects_to_login_when_unauthed(
        self, dashboard_app: FastAPI, path: str, _filename: str
    ) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get(path, follow_redirects=False)
            _assert_redirects_to_login(resp)


@pytest.mark.parametrize(("path", "filename"), _SURFACES)
class TestSurfaceAuthedHappyPath:
    def test_serves_page_when_authed(
        self, authed_dashboard_app: FastAPI, path: str, filename: str
    ) -> None:
        with TestClient(authed_dashboard_app) as client:
            resp = client.get(path, headers={"Authorization": "Bearer test-token"})
            _assert_serves_dashboard_page(resp, filename)


class TestPublicRoutes:
    def test_login_page_is_public(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/login")
            assert resp.status_code == 200
            assert "text/html" in resp.headers["content-type"]

    def test_login_callback_is_public(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/login/callback")
            assert resp.status_code == 200

    def test_logout_clears_cookies(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/logout")
            assert resp.status_code == 200
            # Logout must emit Set-Cookie deletions for every session cookie
            # the app might have set, so that the browser clears them even if
            # the user signs back in under a different identity.
            assert resp.headers.get_list("set-cookie"), "logout must set clearing cookies"


class TestStaticAssets:
    def test_styles_css_is_public(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/styles/colors_and_type.css")
            assert resp.status_code == 200
            assert "text/css" in resp.headers["content-type"]

    def test_component_jsx_is_public(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/components/ui.jsx")
            assert resp.status_code == 200

    def test_svg_asset_is_public(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/assets/logo-seal.svg")
            assert resp.status_code == 200
            assert "image/svg+xml" in resp.headers["content-type"]

    def test_auth_js_is_public(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/auth.js")
            assert resp.status_code == 200
            assert "application/javascript" in resp.headers["content-type"]

    def test_path_traversal_rejected_on_styles(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            # FastAPI rejects traversal at the route level (the {filename}
            # pattern doesn't match paths with slashes), so we get 404.
            resp = client.get("/dashboard/styles/..%2Fauth.js")
            assert resp.status_code == 404

    def test_non_css_filename_rejected(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/styles/evil.js")
            assert resp.status_code == 404

    def test_non_jsx_component_rejected(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/components/evil.js")
            assert resp.status_code == 404

    def test_unknown_asset_ext_rejected(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/assets/evil.exe")
            assert resp.status_code == 404


class TestNonexistentRoutes:
    def test_unknown_dashboard_page_returns_404(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/dashboard/greathall")
            assert resp.status_code == 404

    def test_unknown_top_level_returns_404(self, dashboard_app: FastAPI) -> None:
        with TestClient(dashboard_app) as client:
            resp = client.get("/prompts")
            assert resp.status_code == 404
