"""Constant-time comparison utilities for security-sensitive token checks.

Addresses conductor_security.md #17 #44: Bearer token comparison must be
constant-time to prevent timing side-channel attacks.

Uses ``hmac.compare_digest`` under the hood, which is implemented in C and
runs in constant time regardless of where the first difference occurs.

Usage::

    from stronghold.security.constant_time import secure_compare

    if not secure_compare(user_token, expected_token):
        raise AuthError("Invalid token")
"""

from __future__ import annotations

import hmac


def secure_compare(a: str, b: str) -> bool:
    """Constant-time string comparison.

    Encodes both strings to UTF-8 bytes and delegates to
    ``hmac.compare_digest``. This handles non-ASCII characters
    (which ``compare_digest`` rejects when passed as ``str``).

    Both arguments must be ``str``. For bytes, use :func:`secure_compare_bytes`.
    """
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def secure_compare_bytes(a: bytes, b: bytes) -> bool:
    """Constant-time bytes comparison.

    Wraps ``hmac.compare_digest`` for bytes inputs. Prevents timing
    side-channel attacks on token/key validation.

    Both arguments must be ``bytes``. For strings, use :func:`secure_compare`.
    """
    return hmac.compare_digest(a, b)
