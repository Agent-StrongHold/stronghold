"""Tests for HMAC-SHA256 request signing and verification."""

from __future__ import annotations

import time

import pytest

from stronghold.security.hmac import (
    DEFAULT_MAX_AGE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    sign_request,
    verify_request,
)


class TestSignAndVerifyRoundTrip:
    """Sign a request and verify it succeeds."""

    def test_sign_then_verify_succeeds(self) -> None:
        secret = "test-shared-secret"
        method = "POST"
        path = "/v1/chat/completions"
        body = b'{"message": "hello"}'

        headers = sign_request(
            secret=secret,
            method=method,
            path=path,
            body=body,
        )
        assert verify_request(
            secret=secret,
            method=method,
            path=path,
            body=body,
            signature_header=headers[HEADER_SIGNATURE],
            timestamp_header=headers[HEADER_TIMESTAMP],
        )

    def test_empty_body_roundtrip(self) -> None:
        secret = "test-shared-secret"
        headers = sign_request(secret=secret, method="GET", path="/health")
        assert verify_request(
            secret=secret,
            method="GET",
            path="/health",
            body=b"",
            signature_header=headers[HEADER_SIGNATURE],
            timestamp_header=headers[HEADER_TIMESTAMP],
        )


class TestTamperedPayload:
    """Tampered payloads must fail verification."""

    def test_tampered_body_fails(self) -> None:
        secret = "test-shared-secret"
        headers = sign_request(
            secret=secret,
            method="POST",
            path="/api",
            body=b"original",
        )
        with pytest.raises(ValueError, match="[Ss]ignature"):
            verify_request(
                secret=secret,
                method="POST",
                path="/api",
                body=b"tampered",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
            )

    def test_tampered_path_fails(self) -> None:
        secret = "test-shared-secret"
        headers = sign_request(
            secret=secret,
            method="POST",
            path="/api/v1",
            body=b"data",
        )
        with pytest.raises(ValueError, match="[Ss]ignature"):
            verify_request(
                secret=secret,
                method="POST",
                path="/api/v2",
                body=b"data",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
            )

    def test_tampered_method_fails(self) -> None:
        secret = "test-shared-secret"
        headers = sign_request(
            secret=secret,
            method="POST",
            path="/api",
            body=b"data",
        )
        with pytest.raises(ValueError, match="[Ss]ignature"):
            verify_request(
                secret=secret,
                method="GET",
                path="/api",
                body=b"data",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
            )


class TestTimestampValidation:
    """Timestamp freshness checks."""

    def test_expired_timestamp_fails(self) -> None:
        secret = "test-shared-secret"
        old_ts = time.time() - 120  # 120 seconds ago, well beyond 60s default
        headers = sign_request(
            secret=secret,
            method="GET",
            path="/health",
            timestamp=old_ts,
        )
        with pytest.raises(ValueError, match="[Tt]imestamp"):
            verify_request(
                secret=secret,
                method="GET",
                path="/health",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
            )

    def test_future_timestamp_within_window_succeeds(self) -> None:
        secret = "test-shared-secret"
        future_ts = time.time() + 30  # 30 seconds in the future, within 60s window
        headers = sign_request(
            secret=secret,
            method="GET",
            path="/health",
            timestamp=future_ts,
        )
        assert verify_request(
            secret=secret,
            method="GET",
            path="/health",
            signature_header=headers[HEADER_SIGNATURE],
            timestamp_header=headers[HEADER_TIMESTAMP],
        )

    def test_future_timestamp_beyond_window_fails(self) -> None:
        secret = "test-shared-secret"
        future_ts = time.time() + 120  # 120 seconds in the future, beyond 60s window
        headers = sign_request(
            secret=secret,
            method="GET",
            path="/health",
            timestamp=future_ts,
        )
        with pytest.raises(ValueError, match="[Tt]imestamp"):
            verify_request(
                secret=secret,
                method="GET",
                path="/health",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
            )

    def test_custom_max_age(self) -> None:
        secret = "test-shared-secret"
        old_ts = time.time() - 90  # 90 seconds ago
        headers = sign_request(
            secret=secret,
            method="GET",
            path="/health",
            timestamp=old_ts,
        )
        # Should fail with default 60s window
        with pytest.raises(ValueError, match="[Tt]imestamp"):
            verify_request(
                secret=secret,
                method="GET",
                path="/health",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
                max_age=60,
            )
        # Should succeed with 120s window
        assert verify_request(
            secret=secret,
            method="GET",
            path="/health",
            signature_header=headers[HEADER_SIGNATURE],
            timestamp_header=headers[HEADER_TIMESTAMP],
            max_age=120,
        )


class TestWrongSecret:
    """Wrong secret must fail verification."""

    def test_wrong_secret_fails(self) -> None:
        headers = sign_request(
            secret="secret-one",
            method="POST",
            path="/api",
            body=b"data",
        )
        with pytest.raises(ValueError, match="[Ss]ignature"):
            verify_request(
                secret="secret-two",
                method="POST",
                path="/api",
                body=b"data",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header=headers[HEADER_TIMESTAMP],
            )


class TestMalformedHeaders:
    """Malformed signature headers raise ValueError."""

    def test_missing_sha256_prefix(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        # Strip the "sha256=" prefix
        raw_hex = headers[HEADER_SIGNATURE].removeprefix("sha256=")
        with pytest.raises(ValueError, match="sha256="):
            verify_request(
                secret="test-secret",
                method="GET",
                path="/health",
                signature_header=raw_hex,
                timestamp_header=headers[HEADER_TIMESTAMP],
            )

    def test_empty_signature_header(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        with pytest.raises(ValueError):
            verify_request(
                secret="test-secret",
                method="GET",
                path="/health",
                signature_header="",
                timestamp_header=headers[HEADER_TIMESTAMP],
            )

    def test_non_numeric_timestamp(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        with pytest.raises(ValueError, match="[Tt]imestamp"):
            verify_request(
                secret="test-secret",
                method="GET",
                path="/health",
                signature_header=headers[HEADER_SIGNATURE],
                timestamp_header="not-a-number",
            )


class TestSignRequestOutput:
    """sign_request returns correct header keys and format."""

    def test_returns_correct_header_keys(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        assert HEADER_SIGNATURE in headers
        assert HEADER_TIMESTAMP in headers
        assert len(headers) == 2

    def test_signature_has_sha256_prefix(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        assert headers[HEADER_SIGNATURE].startswith("sha256=")

    def test_timestamp_is_numeric(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        float(headers[HEADER_TIMESTAMP])  # Should not raise

    def test_explicit_timestamp_used(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
            timestamp=1234567890.0,
        )
        assert headers[HEADER_TIMESTAMP] == "1234567890.0"

    def test_signature_is_hex_string(self) -> None:
        headers = sign_request(
            secret="test-secret",
            method="GET",
            path="/health",
        )
        hex_part = headers[HEADER_SIGNATURE].removeprefix("sha256=")
        # SHA-256 hex digest is 64 characters
        assert len(hex_part) == 64
        int(hex_part, 16)  # Should not raise — valid hex


class TestConstantTimeComparison:
    """Verify uses hmac.compare_digest for constant-time comparison."""

    def test_verification_uses_constant_time_comparison(self) -> None:
        """We verify this by checking the module uses hmac.compare_digest.

        Since we can't easily test timing properties in a unit test,
        we inspect the source to ensure compare_digest is used.
        """
        import inspect

        from stronghold.security import hmac as hmac_mod

        source = inspect.getsource(hmac_mod.verify_request)
        assert "compare_digest" in source


class TestDefaultMaxAge:
    """DEFAULT_MAX_AGE constant is 60 seconds."""

    def test_default_max_age_value(self) -> None:
        assert DEFAULT_MAX_AGE == 60
