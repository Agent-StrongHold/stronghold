"""Integration tests for SecurityHeadersMiddleware.

Covers:
- Default security headers on every response
- Server header stripping
- HSTS only when behind HTTPS (X-Forwarded-Proto)
- Custom header overrides via constructor
- Header override can remove a default header (set to empty)
- Headers present on error responses (4xx/5xx)
- Headers present on different HTTP methods (GET, POST, OPTIONS)
- CSP header value
- Permissions-Policy header value
- Referrer-Policy header value

Uses real classes per project rules. No mocks.
asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from starlette.responses import JSONResponse as StarletteJSON
from starlette.routing import Route
from starlette.testclient import TestClient

from stronghold.api.middleware.security_headers import SecurityHeadersMiddleware

if TYPE_CHECKING:
    from starlette.requests import Request as StarletteRequest


# ── Helpers ───────────────────────────────────────────────────────────


def _app(
    overrides: dict[str, str] | None = None,
    force_https: bool = False,
) -> FastAPI:
    """Build a minimal app with SecurityHeadersMiddleware."""

    async def ok(request: StarletteRequest) -> StarletteJSON:
        return StarletteJSON({"ok": True})

    async def error_500(request: StarletteRequest) -> StarletteJSON:
        return StarletteJSON({"error": "boom"}, status_code=500)

    async def error_404(request: StarletteRequest) -> StarletteJSON:
        return StarletteJSON({"error": "not found"}, status_code=404)

    async def echo_method(request: StarletteRequest) -> StarletteJSON:
        return StarletteJSON({"method": request.method})

    async def with_server_header(request: StarletteRequest) -> StarletteJSON:
        return StarletteJSON(
            {"ok": True},
            headers={"Server": "Uvicorn/0.30.0"},
        )

    app = FastAPI(
        routes=[
            Route("/ok", ok, methods=["GET", "POST"]),
            Route("/error-500", error_500, methods=["GET"]),
            Route("/error-404", error_404, methods=["GET"]),
            Route("/echo", echo_method, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
            Route("/server-leak", with_server_header, methods=["GET"]),
        ]
    )
    app.add_middleware(
        SecurityHeadersMiddleware,
        header_overrides=overrides,
        force_https=force_https,
    )
    return app


# ── Default headers ──────────────────────────────────────────────────


class TestDefaultSecurityHeaders:
    """All default security headers are present on a normal 200 response."""

    def test_x_content_type_options(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert resp.status_code == 200
            assert resp.headers["x-content-type-options"] == "nosniff"

    def test_x_frame_options(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert resp.headers["x-frame-options"] == "DENY"

    def test_x_xss_protection(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert resp.headers["x-xss-protection"] == "0"

    def test_content_security_policy(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert resp.headers["content-security-policy"] == "default-src 'self'"

    def test_referrer_policy(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert resp.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


# ── HSTS behaviour ──────────────────────────────────────────────────


class TestHSTSBehaviour:
    """Strict-Transport-Security is only added when behind HTTPS."""

    def test_no_hsts_on_plain_http(self) -> None:
        """Without X-Forwarded-Proto: https, HSTS must NOT be set."""
        with TestClient(_app()) as client:
            resp = client.get("/ok")
            assert "strict-transport-security" not in resp.headers

    def test_hsts_present_with_forwarded_proto_https(self) -> None:
        """With X-Forwarded-Proto: https, HSTS must be set."""
        with TestClient(_app()) as client:
            resp = client.get("/ok", headers={"X-Forwarded-Proto": "https"})
            assert resp.headers["strict-transport-security"] == (
                "max-age=31536000; includeSubDomains"
            )

    def test_hsts_always_present_when_force_https(self) -> None:
        """When force_https=True, HSTS is added regardless of X-Forwarded-Proto."""
        with TestClient(_app(force_https=True)) as client:
            resp = client.get("/ok")
            assert resp.headers["strict-transport-security"] == (
                "max-age=31536000; includeSubDomains"
            )


# ── Server header stripping ─────────────────────────────────────────


class TestServerHeaderStripping:
    """The Server header is removed from responses."""

    def test_server_header_stripped(self) -> None:
        """Even if the app sets a Server header, the middleware removes it."""
        with TestClient(_app()) as client:
            resp = client.get("/server-leak")
            assert "server" not in resp.headers


# ── Custom overrides ────────────────────────────────────────────────


class TestCustomHeaderOverrides:
    """Constructor overrides replace or add headers."""

    def test_override_replaces_default(self) -> None:
        """A custom CSP value replaces the default."""
        custom_csp = "default-src 'self'; script-src 'self' cdn.example.com"
        with TestClient(_app(overrides={"Content-Security-Policy": custom_csp})) as client:
            resp = client.get("/ok")
            assert resp.headers["content-security-policy"] == custom_csp

    def test_override_adds_new_header(self) -> None:
        """An override can add a header not in the defaults."""
        with TestClient(_app(overrides={"X-Custom-Header": "custom-value"})) as client:
            resp = client.get("/ok")
            assert resp.headers["x-custom-header"] == "custom-value"

    def test_override_empty_string_removes_header(self) -> None:
        """Setting a header to empty string removes it from the response."""
        with TestClient(_app(overrides={"X-Frame-Options": ""})) as client:
            resp = client.get("/ok")
            assert "x-frame-options" not in resp.headers


# ── Error responses ─────────────────────────────────────────────────


class TestHeadersOnErrorResponses:
    """Security headers are present on error responses too."""

    def test_headers_on_500(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/error-500")
            assert resp.status_code == 500
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert resp.headers["x-frame-options"] == "DENY"

    def test_headers_on_404(self) -> None:
        with TestClient(_app()) as client:
            resp = client.get("/error-404")
            assert resp.status_code == 404
            assert resp.headers["x-content-type-options"] == "nosniff"
            assert resp.headers["x-frame-options"] == "DENY"


# ── HTTP methods ────────────────────────────────────────────────────


class TestHeadersOnDifferentMethods:
    """Security headers are present regardless of HTTP method."""

    def test_post_has_headers(self) -> None:
        with TestClient(_app()) as client:
            resp = client.post("/ok", json={"foo": "bar"})
            assert resp.status_code == 200
            assert resp.headers["x-content-type-options"] == "nosniff"

    def test_options_has_headers(self) -> None:
        with TestClient(_app()) as client:
            resp = client.options("/echo")
            # OPTIONS may return 405 if not handled, but headers should still be there
            assert resp.headers["x-content-type-options"] == "nosniff"
