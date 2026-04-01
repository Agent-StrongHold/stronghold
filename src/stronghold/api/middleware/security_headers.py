"""Security headers middleware.

Adds defensive HTTP headers to every response:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection: 0  (modern browsers; CSP preferred)
- Content-Security-Policy: default-src 'self'
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: camera=(), microphone=(), geolocation=()
- Strict-Transport-Security (only when behind HTTPS or force_https=True)

Also strips the Server header to avoid leaking server software info.

All default headers can be overridden or removed via the ``header_overrides``
constructor parameter.  Setting a header value to ``""`` removes it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response


# Default security headers applied to every response.
_DEFAULT_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Content-Security-Policy": "default-src 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

_HSTS_VALUE = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every HTTP response.

    Parameters
    ----------
    app:
        The ASGI application to wrap.
    header_overrides:
        Optional dict of header name → value.  Overrides defaults.
        Set a value to ``""`` to remove that header entirely.
    force_https:
        When ``True``, always emit the ``Strict-Transport-Security``
        header regardless of ``X-Forwarded-Proto``.  Useful when TLS
        termination happens outside the proxy chain visible to the app.
    """

    def __init__(
        self,
        app: Any,
        header_overrides: dict[str, str] | None = None,
        force_https: bool = False,
    ) -> None:
        super().__init__(app)
        # Merge defaults with overrides; store the final map.
        self._headers: dict[str, str] = {**_DEFAULT_HEADERS}
        if header_overrides:
            self._headers.update(header_overrides)
        self._force_https = force_https

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[..., Any],
    ) -> Response:
        response: Response = await call_next(request)

        # Apply all configured headers.
        for name, value in self._headers.items():
            if value:
                response.headers[name] = value
            elif name.lower() in {k.lower() for k in response.headers}:
                # Empty string means "remove this header".
                del response.headers[name]

        # HSTS: only when the connection is HTTPS (or forced).
        is_https = (
            self._force_https or request.headers.get("x-forwarded-proto", "").lower() == "https"
        )
        if is_https:
            response.headers["Strict-Transport-Security"] = _HSTS_VALUE

        # Strip Server header to avoid leaking software info.
        if "server" in {k.lower() for k in response.headers}:
            del response.headers["server"]

        return response
