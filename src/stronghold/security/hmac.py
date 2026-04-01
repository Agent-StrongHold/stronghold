"""HMAC-SHA256 request signing and verification for internal service calls.

Provides two public functions:
  - ``sign_request`` — creates signature headers for an outbound request.
  - ``verify_request`` — validates signature and checks timestamp freshness.

Signing payload format::

    {METHOD}\\n{PATH}\\n{TIMESTAMP}\\n{BODY_BYTES}

Headers produced / consumed:
  - ``X-Stronghold-Signature: sha256=<hex_digest>``
  - ``X-Stronghold-Timestamp: <unix_epoch_float>``
"""

from __future__ import annotations

import hashlib
import hmac
import time

__all__ = [
    "DEFAULT_MAX_AGE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "sign_request",
    "verify_request",
]

HEADER_SIGNATURE = "X-Stronghold-Signature"
HEADER_TIMESTAMP = "X-Stronghold-Timestamp"
DEFAULT_MAX_AGE: float = 60  # seconds


def _build_payload(method: str, path: str, timestamp: float, body: bytes) -> bytes:
    """Construct the canonical signing payload."""
    prefix = f"{method}\n{path}\n{timestamp}\n".encode()
    return prefix + body


def sign_request(
    *,
    secret: str,
    method: str,
    path: str,
    body: bytes = b"",
    timestamp: float | None = None,
) -> dict[str, str]:
    """Create HMAC-SHA256 signature headers for an outbound request.

    Returns a dict with ``X-Stronghold-Signature`` and ``X-Stronghold-Timestamp``
    headers suitable for attaching to an HTTP request.

    Args:
        secret: Shared secret for the target backend.
        method: HTTP method (e.g. ``"POST"``).
        path: Request path (e.g. ``"/v1/chat/completions"``).
        body: Raw request body bytes. Defaults to empty.
        timestamp: Unix epoch float. Defaults to ``time.time()``.

    Returns:
        Dict with two header entries.
    """
    if timestamp is None:
        timestamp = time.time()

    payload = _build_payload(method, path, timestamp, body)
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    return {
        HEADER_SIGNATURE: f"sha256={digest}",
        HEADER_TIMESTAMP: str(timestamp),
    }


def verify_request(
    *,
    secret: str,
    method: str,
    path: str,
    body: bytes = b"",
    signature_header: str,
    timestamp_header: str,
    max_age: float = DEFAULT_MAX_AGE,
) -> bool:
    """Verify HMAC-SHA256 signature and timestamp freshness.

    Returns ``True`` when the signature is valid **and** the timestamp is
    within *max_age* seconds of the current time.

    Raises:
        ValueError: If the signature is invalid, the timestamp is stale /
            too far in the future, or the header format is malformed.

    Args:
        secret: Shared secret for this backend.
        method: HTTP method used in the original request.
        path: Request path used in the original request.
        body: Raw request body bytes. Defaults to empty.
        signature_header: Value of ``X-Stronghold-Signature`` header.
        timestamp_header: Value of ``X-Stronghold-Timestamp`` header.
        max_age: Maximum allowed age in seconds (default 60).
    """
    # ── Validate header format ──────────────────────────────────────
    if not signature_header.startswith("sha256="):
        msg = "Signature header must start with 'sha256=' prefix"
        raise ValueError(msg)

    # ── Parse timestamp ─────────────────────────────────────────────
    try:
        timestamp = float(timestamp_header)
    except (ValueError, TypeError) as exc:
        msg = f"Timestamp header is not a valid number: {timestamp_header!r}"
        raise ValueError(msg) from exc

    # ── Check freshness ─────────────────────────────────────────────
    age = abs(time.time() - timestamp)
    if age > max_age:
        msg = f"Timestamp is stale: {age:.1f}s old, max allowed is {max_age:.1f}s"
        raise ValueError(msg)

    # ── Recompute and compare (constant-time) ───────────────────────
    payload = _build_payload(method, path, timestamp, body)
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    received = signature_header.removeprefix("sha256=")
    if not hmac.compare_digest(expected, received):
        msg = "Signature mismatch"
        raise ValueError(msg)

    return True
