"""Tests for standardized error response format.

Covers:
- ErrorResponse dataclass construction and serialization
- format_error() for StrongholdError hierarchy and generic exceptions
- stronghold_exception_handler returns correct status codes per error type
- generic_exception_handler sanitizes stack traces in production
- register_error_handlers wires both handlers onto a FastAPI app
- Request ID propagation from headers
- Detail field is optional and omitted when empty

Uses real classes per project rules. No mocks.
asyncio_mode = "auto" — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from starlette.testclient import TestClient

if TYPE_CHECKING:
    from fastapi.responses import JSONResponse

from stronghold.api.error_handler import (
    ErrorResponse,
    format_error,
    register_error_handlers,
)
from stronghold.types.errors import (
    AuthError,
    ClassificationError,
    ConfigError,
    InjectionError,
    NoModelsError,
    PermissionDeniedError,
    QuotaExhaustedError,
    RoutingError,
    SecurityError,
    SkillError,
    StrongholdError,
    TokenExpiredError,
    ToolError,
    TrustViolationError,
)

# ── ErrorResponse dataclass ──────────────────────────────────────────


class TestErrorResponse:
    """ErrorResponse construction and serialization."""

    def test_minimal_construction(self) -> None:
        resp = ErrorResponse(code="TEST_ERROR", message="something broke")
        assert resp.status == "error"
        assert resp.code == "TEST_ERROR"
        assert resp.message == "something broke"
        assert resp.detail is None
        assert resp.request_id is None

    def test_full_construction(self) -> None:
        resp = ErrorResponse(
            code="AUTH_ERROR",
            message="bad token",
            detail="JWT signature mismatch",
            request_id="req-abc-123",
        )
        assert resp.status == "error"
        assert resp.code == "AUTH_ERROR"
        assert resp.detail == "JWT signature mismatch"
        assert resp.request_id == "req-abc-123"

    def test_to_dict_omits_none_fields(self) -> None:
        resp = ErrorResponse(code="X", message="y")
        d = resp.to_dict()
        assert "detail" not in d
        assert "request_id" not in d
        assert d["status"] == "error"
        assert d["code"] == "X"
        assert d["message"] == "y"

    def test_to_dict_includes_present_fields(self) -> None:
        resp = ErrorResponse(code="X", message="y", detail="z", request_id="r1")
        d = resp.to_dict()
        assert d["detail"] == "z"
        assert d["request_id"] == "r1"


# ── format_error ─────────────────────────────────────────────────────


class TestFormatError:
    """format_error converts exceptions to standard JSON dicts."""

    def test_stronghold_error_base(self) -> None:
        exc = StrongholdError("base failure")
        result = format_error(exc)
        assert result["status"] == "error"
        assert result["code"] == "STRONGHOLD_ERROR"
        assert result["message"] == "base failure"

    def test_auth_error_with_code(self) -> None:
        exc = AuthError("not authenticated")
        result = format_error(exc)
        assert result["code"] == "AUTH_ERROR"
        assert result["message"] == "not authenticated"

    def test_generic_exception_hides_details(self) -> None:
        exc = RuntimeError("leaked database password xyz")
        result = format_error(exc)
        assert result["code"] == "INTERNAL_ERROR"
        assert "database password" not in result["message"]
        assert result["message"] == "An internal error occurred"

    def test_request_id_propagated(self) -> None:
        exc = RoutingError("no route")
        result = format_error(exc, request_id="req-999")
        assert result["request_id"] == "req-999"

    def test_stronghold_error_detail_preserved(self) -> None:
        exc = SecurityError("blocked", code="CUSTOM_SEC")
        result = format_error(exc)
        assert result["code"] == "CUSTOM_SEC"
        assert result["message"] == "blocked"


# ── HTTP status mapping ──────────────────────────────────────────────


def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with error handlers registered."""
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise-stronghold")
    async def raise_stronghold() -> JSONResponse:
        raise StrongholdError("base error")

    @app.get("/raise-auth")
    async def raise_auth() -> JSONResponse:
        raise AuthError("unauthorized")

    @app.get("/raise-token-expired")
    async def raise_token_expired() -> JSONResponse:
        raise TokenExpiredError("token expired")

    @app.get("/raise-permission")
    async def raise_permission() -> JSONResponse:
        raise PermissionDeniedError("forbidden")

    @app.get("/raise-security")
    async def raise_security() -> JSONResponse:
        raise SecurityError("threat detected")

    @app.get("/raise-injection")
    async def raise_injection() -> JSONResponse:
        raise InjectionError("prompt injection")

    @app.get("/raise-trust")
    async def raise_trust() -> JSONResponse:
        raise TrustViolationError("trust violation")

    @app.get("/raise-routing")
    async def raise_routing() -> JSONResponse:
        raise RoutingError("no route")

    @app.get("/raise-quota")
    async def raise_quota() -> JSONResponse:
        raise QuotaExhaustedError("quota exhausted")

    @app.get("/raise-no-models")
    async def raise_no_models() -> JSONResponse:
        raise NoModelsError("no models")

    @app.get("/raise-classification")
    async def raise_classification() -> JSONResponse:
        raise ClassificationError("classification failed")

    @app.get("/raise-tool")
    async def raise_tool() -> JSONResponse:
        raise ToolError("tool broke")

    @app.get("/raise-config")
    async def raise_config() -> JSONResponse:
        raise ConfigError("bad config")

    @app.get("/raise-skill")
    async def raise_skill() -> JSONResponse:
        raise SkillError("skill failed")

    @app.get("/raise-generic")
    async def raise_generic() -> JSONResponse:
        raise RuntimeError("unexpected internal error with secrets")

    @app.get("/raise-value-error")
    async def raise_value_error() -> JSONResponse:
        raise ValueError("bad input value")

    return app


class TestStrongholdExceptionHandler:
    """stronghold_exception_handler returns correct HTTP status codes."""

    def setup_method(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_base_stronghold_error_500(self) -> None:
        resp = self.client.get("/raise-stronghold")
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["code"] == "STRONGHOLD_ERROR"

    def test_auth_error_401(self) -> None:
        resp = self.client.get("/raise-auth")
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_ERROR"

    def test_token_expired_401(self) -> None:
        resp = self.client.get("/raise-token-expired")
        assert resp.status_code == 401
        assert resp.json()["code"] == "TOKEN_EXPIRED"

    def test_permission_denied_403(self) -> None:
        resp = self.client.get("/raise-permission")
        assert resp.status_code == 403
        assert resp.json()["code"] == "PERMISSION_DENIED"

    def test_security_error_403(self) -> None:
        resp = self.client.get("/raise-security")
        assert resp.status_code == 403
        assert resp.json()["code"] == "SECURITY_ERROR"

    def test_injection_error_403(self) -> None:
        resp = self.client.get("/raise-injection")
        assert resp.status_code == 403
        assert resp.json()["code"] == "INJECTION_DETECTED"

    def test_trust_violation_403(self) -> None:
        resp = self.client.get("/raise-trust")
        assert resp.status_code == 403
        assert resp.json()["code"] == "TRUST_VIOLATION"

    def test_routing_error_502(self) -> None:
        resp = self.client.get("/raise-routing")
        assert resp.status_code == 502
        assert resp.json()["code"] == "ROUTING_ERROR"

    def test_quota_exhausted_429(self) -> None:
        resp = self.client.get("/raise-quota")
        assert resp.status_code == 429
        assert resp.json()["code"] == "QUOTA_EXHAUSTED"

    def test_no_models_503(self) -> None:
        resp = self.client.get("/raise-no-models")
        assert resp.status_code == 503
        assert resp.json()["code"] == "NO_MODELS_AVAILABLE"

    def test_classification_error_422(self) -> None:
        resp = self.client.get("/raise-classification")
        assert resp.status_code == 422
        assert resp.json()["code"] == "CLASSIFICATION_ERROR"

    def test_tool_error_502(self) -> None:
        resp = self.client.get("/raise-tool")
        assert resp.status_code == 502
        assert resp.json()["code"] == "TOOL_ERROR"

    def test_config_error_500(self) -> None:
        resp = self.client.get("/raise-config")
        assert resp.status_code == 500
        assert resp.json()["code"] == "CONFIG_ERROR"

    def test_skill_error_500(self) -> None:
        resp = self.client.get("/raise-skill")
        assert resp.status_code == 500
        assert resp.json()["code"] == "SKILL_ERROR"


class TestGenericExceptionHandler:
    """generic_exception_handler sanitizes details for non-Stronghold errors."""

    def setup_method(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_generic_error_500(self) -> None:
        resp = self.client.get("/raise-generic")
        assert resp.status_code == 500
        body = resp.json()
        assert body["status"] == "error"
        assert body["code"] == "INTERNAL_ERROR"
        assert "secrets" not in body["message"]
        assert body["message"] == "An internal error occurred"

    def test_value_error_400(self) -> None:
        resp = self.client.get("/raise-value-error")
        assert resp.status_code == 400
        body = resp.json()
        assert body["code"] == "VALIDATION_ERROR"
        assert body["message"] == "bad input value"


class TestRequestIdPropagation:
    """Request ID from X-Request-ID header appears in error responses."""

    def setup_method(self) -> None:
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_request_id_in_stronghold_error(self) -> None:
        resp = self.client.get("/raise-auth", headers={"X-Request-ID": "req-abc-123"})
        body = resp.json()
        assert body["request_id"] == "req-abc-123"

    def test_request_id_in_generic_error(self) -> None:
        resp = self.client.get("/raise-generic", headers={"X-Request-ID": "req-xyz-789"})
        body = resp.json()
        assert body["request_id"] == "req-xyz-789"

    def test_no_request_id_header_omits_field(self) -> None:
        resp = self.client.get("/raise-auth")
        body = resp.json()
        assert "request_id" not in body


class TestRegisterErrorHandlers:
    """register_error_handlers wires both handlers onto a FastAPI app."""

    def test_registers_both_handlers(self) -> None:
        app = FastAPI()
        register_error_handlers(app)
        # FastAPI stores exception handlers in a dict keyed by exception type
        assert StrongholdError in app.exception_handlers
        assert Exception in app.exception_handlers
