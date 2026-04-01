"""Tests for constant-time token comparison utility.

Addresses conductor_security.md #17 #44: Bearer token comparison not constant-time.
Validates that secure_compare and secure_compare_bytes wrap hmac.compare_digest
correctly for all edge cases.
"""

from __future__ import annotations

from stronghold.security.constant_time import secure_compare, secure_compare_bytes

# ---------------------------------------------------------------------------
# secure_compare (str)
# ---------------------------------------------------------------------------


class TestSecureCompare:
    """Tests for string-based constant-time comparison."""

    def test_equal_strings_return_true(self) -> None:
        assert secure_compare("secret-token-abc", "secret-token-abc") is True

    def test_different_strings_return_false(self) -> None:
        assert secure_compare("secret-token-abc", "secret-token-xyz") is False

    def test_different_lengths_return_false(self) -> None:
        assert secure_compare("short", "a-much-longer-string") is False

    def test_empty_strings_return_true(self) -> None:
        assert secure_compare("", "") is True

    def test_empty_vs_nonempty_returns_false(self) -> None:
        assert secure_compare("", "nonempty") is False

    def test_nonempty_vs_empty_returns_false(self) -> None:
        assert secure_compare("nonempty", "") is False

    def test_unicode_equal(self) -> None:
        assert secure_compare("tök€n-ünîcödé", "tök€n-ünîcödé") is True

    def test_unicode_different(self) -> None:
        assert secure_compare("tök€n-a", "tök€n-b") is False

    def test_single_char_difference(self) -> None:
        assert secure_compare("abcdefg", "abcdefh") is False

    def test_whitespace_matters(self) -> None:
        assert secure_compare("token ", "token") is False

    def test_case_sensitive(self) -> None:
        assert secure_compare("Token", "token") is False


# ---------------------------------------------------------------------------
# secure_compare_bytes (bytes)
# ---------------------------------------------------------------------------


class TestSecureCompareBytes:
    """Tests for bytes-based constant-time comparison."""

    def test_equal_bytes_return_true(self) -> None:
        assert secure_compare_bytes(b"secret", b"secret") is True

    def test_different_bytes_return_false(self) -> None:
        assert secure_compare_bytes(b"secret", b"notsec") is False

    def test_different_lengths_return_false(self) -> None:
        assert secure_compare_bytes(b"ab", b"abcdef") is False

    def test_empty_bytes_return_true(self) -> None:
        assert secure_compare_bytes(b"", b"") is True

    def test_empty_vs_nonempty_returns_false(self) -> None:
        assert secure_compare_bytes(b"", b"data") is False

    def test_nonempty_vs_empty_returns_false(self) -> None:
        assert secure_compare_bytes(b"data", b"") is False

    def test_binary_data(self) -> None:
        a = bytes(range(256))
        b = bytes(range(256))
        assert secure_compare_bytes(a, b) is True

    def test_binary_data_different(self) -> None:
        a = bytes(range(256))
        b = bytes((x + 1) % 256 for x in range(256))
        assert secure_compare_bytes(a, b) is False
