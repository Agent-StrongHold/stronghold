"""Comprehensive tests for Sentinel PII filter: detection, redaction, edge cases.

Covers every pattern category in the PII filter (AWS keys, GitHub/GitLab tokens,
API keys, bearer tokens, JWTs, connection strings, IP addresses, emails, private
keys, passwords) plus redaction formatting, Unicode normalization, overlap handling,
and false-positive resistance.
"""

from __future__ import annotations

from stronghold.security.sentinel.pii_filter import (
    PIIMatch,
    redact,
    scan_and_redact,
    scan_for_pii,
)

# ── AWS Key Detection ──────────────────────────────────────────────────


class TestAWSKeyDetection:
    """AWS access key ID pattern: AKIA followed by 16 uppercase alphanumeric."""

    def test_valid_aws_key_detected(self) -> None:
        matches = scan_for_pii("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE")
        assert len(matches) == 1
        assert matches[0].pii_type == "aws_key"
        assert matches[0].value == "AKIAIOSFODNN7EXAMPLE"

    def test_aws_key_embedded_in_config_block(self) -> None:
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\naws_secret_access_key = wJal..."
        matches = [m for m in scan_for_pii(text) if m.pii_type == "aws_key"]
        assert len(matches) == 1

    def test_akia_prefix_too_short_not_detected(self) -> None:
        """AKIA followed by fewer than 16 chars should not match."""
        matches = scan_for_pii("AKIA12345")
        assert not any(m.pii_type == "aws_key" for m in matches)


# ── GitHub / GitLab Token Detection ────────────────────────────────────


class TestGitHubTokenDetection:
    """GitHub classic PATs (ghp_), fine-grained PATs (github_pat_), and org tokens."""

    def test_ghp_classic_token(self) -> None:
        token = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        matches = scan_for_pii(f"GITHUB_TOKEN={token}")
        assert any(m.pii_type == "github_token" for m in matches)

    def test_gho_oauth_token(self) -> None:
        token = "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        matches = scan_for_pii(token)
        assert any(m.pii_type == "github_token" for m in matches)

    def test_github_fine_grained_pat(self) -> None:
        token = "github_pat_11ABCDEFGH0123456789_abcdefghijklmnopqrstuvwxyz"
        matches = scan_for_pii(f"Authorization: token {token}")
        assert any(m.pii_type == "github_token" for m in matches)

    def test_gitlab_token(self) -> None:
        token = "glpat-xYzAbCdEfGhIjKlMnOpQr"
        matches = scan_for_pii(f"GITLAB_TOKEN={token}")
        assert any(m.pii_type == "gitlab_token" for m in matches)


# ── Generic API Key Detection ──────────────────────────────────────────


class TestAPIKeyDetection:
    """sk- prefix keys and key=value assignment patterns."""

    def test_sk_prefix_api_key(self) -> None:
        key = "sk-proj-abc123def456ghi789jkl012"
        matches = scan_for_pii(f"OPENAI_API_KEY={key}")
        assert any(m.pii_type == "api_key" for m in matches)

    def test_api_key_equals_quoted(self) -> None:
        matches = scan_for_pii('api_key = "xK9mP2nQ4rS6tU8vW0yZ1234"')
        assert any(m.pii_type == "api_key" for m in matches)

    def test_secret_key_colon(self) -> None:
        matches = scan_for_pii("secret_key: abcdef1234567890abcdef")
        assert any(m.pii_type == "api_key" for m in matches)

    def test_access_token_case_insensitive(self) -> None:
        matches = scan_for_pii("ACCESS_TOKEN=abcdef1234567890abcdef")
        assert any(m.pii_type == "api_key" for m in matches)

    def test_auth_token_assignment(self) -> None:
        matches = scan_for_pii('auth_token: "aBcDeFgHiJkLmNoPqRsTuVwX"')
        assert any(m.pii_type == "api_key" for m in matches)


# ── Bearer Token Detection ────────────────────────────────────────────


class TestBearerTokenDetection:
    """Bearer tokens in Authorization headers."""

    def test_bearer_with_opaque_token(self) -> None:
        matches = scan_for_pii("Authorization: Bearer xK9mP2nQ4rS6tU8vW0yZaBcDeFgHiJkLm")
        assert any(m.pii_type == "bearer_token" for m in matches)


# ── IP Address Detection ──────────────────────────────────────────────


class TestIPAddressDetection:
    """IPv4 detection with allowlist for safe addresses."""

    def test_private_class_a(self) -> None:
        matches = scan_for_pii("Host: 10.0.1.50")
        assert any(m.pii_type == "ip_address" for m in matches)

    def test_private_class_c(self) -> None:
        matches = scan_for_pii("Server 192.168.1.100 is down")
        assert any(m.pii_type == "ip_address" for m in matches)

    def test_public_ip(self) -> None:
        matches = scan_for_pii("External IP: 203.0.113.42")
        assert any(m.pii_type == "ip_address" for m in matches)

    def test_loopback_127_0_0_1_skipped(self) -> None:
        matches = scan_for_pii("Listen on 127.0.0.1:8080")
        assert not any(m.pii_type == "ip_address" for m in matches)

    def test_all_zeros_skipped(self) -> None:
        matches = scan_for_pii("Bind 0.0.0.0 to all interfaces")
        assert not any(m.pii_type == "ip_address" for m in matches)

    def test_broadcast_255_skipped(self) -> None:
        matches = scan_for_pii("Broadcast 255.255.255.255")
        assert not any(m.pii_type == "ip_address" for m in matches)

    def test_version_number_not_flagged(self) -> None:
        """Three-part version strings like 3.12.1 should not match."""
        matches = scan_for_pii("Upgraded to Python 3.12.1 today")
        assert not any(m.pii_type == "ip_address" for m in matches)


# ── Email Detection ───────────────────────────────────────────────────


class TestEmailDetection:
    """RFC-style email patterns."""

    def test_simple_email(self) -> None:
        matches = scan_for_pii("Contact admin@stronghold.io for support")
        assert len(matches) == 1
        assert matches[0].pii_type == "email"
        assert matches[0].value == "admin@stronghold.io"

    def test_plus_tagged_email(self) -> None:
        matches = scan_for_pii("Send to user+alerts@sub.domain.org")
        assert any(m.pii_type == "email" for m in matches)

    def test_dotted_local_part(self) -> None:
        matches = scan_for_pii("first.last@company.co.uk")
        assert any(m.pii_type == "email" for m in matches)


# ── JWT Detection ─────────────────────────────────────────────────────


class TestJWTDetection:
    """JWT tokens: three dot-separated base64url segments starting with eyJ."""

    def test_standard_jwt(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        matches = scan_for_pii(f"Set-Cookie: token={jwt}")
        assert any(m.pii_type == "jwt" for m in matches)

    def test_jwt_embedded_in_json(self) -> None:
        jwt = "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiJzdHJvbmdob2xkIn0.c2lnbmF0dXJlZGF0YWhlcmU"
        matches = scan_for_pii(f'{{"access_token": "{jwt}"}}')
        assert any(m.pii_type == "jwt" for m in matches)


# ── Connection String Detection ───────────────────────────────────────


class TestConnectionStringDetection:
    """Database and message broker URIs."""

    def test_postgres_with_password(self) -> None:
        dsn = "postgres://admin:s3cret@db.prod.internal:5432/stronghold"
        matches = scan_for_pii(f"DATABASE_URL={dsn}")
        assert any(m.pii_type == "connection_string" for m in matches)

    def test_mysql_url(self) -> None:
        matches = scan_for_pii("mysql://root:pass@mysql.svc:3306/app")
        assert any(m.pii_type == "connection_string" for m in matches)

    def test_mongodb_srv(self) -> None:
        matches = scan_for_pii("mongodb+srv://user:pw@cluster.mongodb.net/db")
        assert any(m.pii_type == "connection_string" for m in matches)

    def test_redis_url(self) -> None:
        matches = scan_for_pii("redis://default:token@redis.internal:6379/0")
        assert any(m.pii_type == "connection_string" for m in matches)

    def test_amqp_url(self) -> None:
        matches = scan_for_pii("amqp://guest:guest@rabbitmq.svc:5672/vhost")
        assert any(m.pii_type == "connection_string" for m in matches)


# ── Private Key Detection ─────────────────────────────────────────────


class TestPrivateKeyDetection:
    """PEM-encoded private key header blocks."""

    def test_rsa_private_key(self) -> None:
        matches = scan_for_pii("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...")
        assert any(m.pii_type == "private_key" for m in matches)

    def test_ec_private_key(self) -> None:
        matches = scan_for_pii("-----BEGIN EC PRIVATE KEY-----\nMHQCAQ...")
        assert any(m.pii_type == "private_key" for m in matches)

    def test_openssh_private_key(self) -> None:
        matches = scan_for_pii("-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blb...")
        assert any(m.pii_type == "private_key" for m in matches)

    def test_generic_private_key(self) -> None:
        matches = scan_for_pii("-----BEGIN PRIVATE KEY-----\nMIIEvQ...")
        assert any(m.pii_type == "private_key" for m in matches)


# ── Password Detection ────────────────────────────────────────────────


class TestPasswordDetection:
    """Password-like assignments in config/logs."""

    def test_password_equals(self) -> None:
        matches = scan_for_pii('password = "SuperSecret123!"')
        assert any(m.pii_type == "password" for m in matches)

    def test_passwd_colon(self) -> None:
        matches = scan_for_pii("passwd: MyLongPassword99")
        assert any(m.pii_type == "password" for m in matches)

    def test_pwd_equals(self) -> None:
        matches = scan_for_pii("pwd=X8kMnP2qR4sT6uV8")
        assert any(m.pii_type == "password" for m in matches)

    def test_short_password_not_flagged(self) -> None:
        """Values under 8 characters should not trigger the password pattern."""
        matches = scan_for_pii("password = short")
        assert not any(m.pii_type == "password" for m in matches)


# ── System Prompt Leak Detection ──────────────────────────────────────


class TestSystemPromptLeakDetection:
    """Ensure system prompt content with embedded secrets is caught.

    The PII filter does not have a dedicated "system prompt leak" pattern,
    but it should catch any secrets embedded in leaked prompt text.
    """

    def test_leaked_prompt_with_api_key(self) -> None:
        leaked = (
            "System prompt: You are an assistant. "
            "Use api_key = xK9mP2nQ4rS6tU8vW0yZ1234 to call the API."
        )
        matches = scan_for_pii(leaked)
        assert any(m.pii_type == "api_key" for m in matches)

    def test_leaked_prompt_with_connection_string(self) -> None:
        leaked = (
            "Internal config: connect to postgres://admin:s3cret@10.0.1.5:5432/prod for user data."
        )
        matches = scan_for_pii(leaked)
        types = {m.pii_type for m in matches}
        assert "connection_string" in types


# ── Redaction Format ──────────────────────────────────────────────────


class TestRedactionFormat:
    """Verify redaction placeholder format: [REDACTED:<type>]."""

    def test_placeholder_format_aws_key(self) -> None:
        result = redact("Key: AKIAIOSFODNN7EXAMPLE here")
        assert "[REDACTED:aws_key]" in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_placeholder_format_email(self) -> None:
        result = redact("Contact admin@stronghold.io please")
        assert "[REDACTED:email]" in result
        assert "admin@stronghold.io" not in result

    def test_placeholder_format_ip(self) -> None:
        result = redact("Server at 10.0.1.50")
        assert "[REDACTED:ip_address]" in result

    def test_placeholder_format_jwt(self) -> None:
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        result = redact(f"token={jwt}")
        assert "[REDACTED:jwt]" in result
        assert jwt not in result

    def test_multiple_redactions_preserve_surrounding_text(self) -> None:
        text = "User admin@example.com logged in from 10.0.1.50 successfully"
        result = redact(text)
        assert result.startswith("User ")
        assert result.endswith(" successfully")
        assert "[REDACTED:email]" in result
        assert "[REDACTED:ip_address]" in result


# ── Clean Text Passes Through ─────────────────────────────────────────


class TestCleanTextPassthrough:
    """Normal conversational text should not be flagged or altered."""

    def test_simple_greeting(self) -> None:
        text = "Hello, how can I help you today?"
        assert scan_for_pii(text) == []
        assert redact(text) == text

    def test_code_discussion(self) -> None:
        text = "The function returns True when the input passes validation."
        assert scan_for_pii(text) == []

    def test_markdown_content(self) -> None:
        text = "## Architecture\n\nThe system uses a **protocol-driven** DI container."
        assert scan_for_pii(text) == []

    def test_numeric_content(self) -> None:
        text = "The server processed 1,234,567 requests in 42.5 seconds."
        assert scan_for_pii(text) == []


# ── PIIMatch Dataclass ────────────────────────────────────────────────


class TestPIIMatchDataclass:
    """PIIMatch is frozen and contains correct offsets."""

    def test_match_fields(self) -> None:
        matches = scan_for_pii("Found AKIAIOSFODNN7EXAMPLE in logs")
        assert len(matches) == 1
        m = matches[0]
        assert m.pii_type == "aws_key"
        assert m.value == "AKIAIOSFODNN7EXAMPLE"
        assert m.start == 6
        assert m.end == 26

    def test_match_is_frozen(self) -> None:
        m = PIIMatch(pii_type="email", value="a@b.co", start=0, end=6)
        try:
            m.pii_type = "other"  # type: ignore[misc]
            raise AssertionError("Should have raised FrozenInstanceError")
        except AttributeError:
            pass  # Expected: frozen dataclass


# ── scan_and_redact Convenience ───────────────────────────────────────


class TestScanAndRedact:
    """The scan_and_redact helper returns both redacted text and matches."""

    def test_returns_tuple(self) -> None:
        redacted, matches = scan_and_redact("Server at 192.168.1.100")
        assert isinstance(redacted, str)
        assert isinstance(matches, list)
        assert len(matches) == 1
        assert "192.168.1.100" not in redacted

    def test_clean_text_returns_original(self) -> None:
        text = "Nothing sensitive here."
        redacted, matches = scan_and_redact(text)
        assert redacted == text
        assert matches == []


# ── Overlap Handling ──────────────────────────────────────────────────


class TestOverlapHandling:
    """Overlapping pattern ranges should not produce duplicate matches."""

    def test_bearer_jwt_overlap(self) -> None:
        """A Bearer header carrying a JWT should not double-match."""
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.c2lnbmF0dXJlZGF0YQ"
        text = f"Authorization: Bearer {jwt}"
        matches = scan_for_pii(text)
        # First match is bearer_token; JWT overlaps so it should be suppressed
        starts = [m.start for m in matches]
        assert len(starts) == len(set(starts)), "Duplicate start offsets found"

    def test_sk_key_inside_generic_pattern(self) -> None:
        """An sk- key in an api_key= assignment: first matched pattern wins."""
        text = "api_key = sk-proj-abc123def456ghi789jkl012"
        matches = scan_for_pii(text)
        # Should detect it but not produce overlapping matches
        assert len(matches) >= 1
        ranges = [(m.start, m.end) for m in matches]
        for i, (s1, e1) in enumerate(ranges):
            for s2, e2 in ranges[i + 1 :]:
                assert e1 <= s2 or e2 <= s1, f"Overlap: ({s1},{e1}) vs ({s2},{e2})"


# ── Redaction Idempotency ────────────────────────────────────────────


class TestRedactionIdempotency:
    """Redacting already-redacted text should not nest placeholders."""

    def test_double_redact_is_stable(self) -> None:
        text = "Key: AKIAIOSFODNN7EXAMPLE and admin@example.com"
        first = redact(text)
        second = redact(first)
        assert first == second

    def test_redact_with_explicit_empty_matches(self) -> None:
        text = "Nothing here"
        assert redact(text, matches=[]) == text


# ── Unicode / Homoglyph Normalization ────────────────────────────────


class TestUnicodeNormalization:
    """scan_for_pii normalizes NFKD to defeat homoglyph evasion."""

    def test_fullwidth_digits_in_ip(self) -> None:
        """Full-width digits (\uff11\uff10.\uff10.\uff11.\uff15\uff10) normalize to ASCII."""
        # \uff11 = fullwidth 1, \uff10 = fullwidth 0, etc.
        # NFKD normalizes fullwidth digits to ASCII
        fullwidth = "\uff11\uff10.\uff10.\uff11.\uff15\uff10"
        matches = scan_for_pii(fullwidth)
        assert any(m.pii_type == "ip_address" for m in matches)

    def test_normal_ascii_unaffected(self) -> None:
        """ASCII text should pass through normalization unchanged."""
        text = "AKIAIOSFODNN7EXAMPLE"
        matches = scan_for_pii(text)
        assert len(matches) == 1
        assert matches[0].pii_type == "aws_key"


# ── Matches Sorted by Position ───────────────────────────────────────


class TestMatchOrdering:
    """scan_for_pii returns matches sorted by start offset."""

    def test_multiple_matches_sorted(self) -> None:
        text = "admin@example.com then 10.0.1.50 then AKIAIOSFODNN7EXAMPLE"
        matches = scan_for_pii(text)
        assert len(matches) == 3
        starts = [m.start for m in matches]
        assert starts == sorted(starts), f"Not sorted: {starts}"
        assert matches[0].pii_type == "email"
        assert matches[1].pii_type == "ip_address"
        assert matches[2].pii_type == "aws_key"
