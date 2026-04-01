"""Comprehensive tests for config/loader.py (load_config) and config/defaults.py.

Covers: YAML loading, env-var overrides, default values, private-IP blocking
in URLs, invalid config handling, CORS validation, secret length enforcement,
and nested auth overrides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from stronghold.config.loader import _validate_url_not_private, load_config
from stronghold.types.config import (
    CORSConfig,
    RateLimitConfig,
    RoutingConfig,
    SecurityConfig,
    SessionsConfig,
    StrongholdConfig,
)


class TestLoadConfigYAML:
    """YAML file loading: valid, invalid, empty, missing."""

    def test_valid_yaml_populates_all_fields(self, tmp_path: Path) -> None:
        """A full YAML file is parsed into the corresponding config fields."""
        yaml_content = """\
router_api_key: sk-yaml-key-abc
litellm_url: http://litellm:4000
litellm_key: sk-litellm-key
database_url: postgresql://u:p@host:5432/db
routing:
  quality_weight: 0.7
  cost_weight: 0.3
sessions:
  max_messages: 50
  ttl_seconds: 7200
security:
  warden_enabled: false
"""
        f = tmp_path / "full.yaml"
        f.write_text(yaml_content)
        config = load_config(f)

        assert config.router_api_key == "sk-yaml-key-abc"
        assert config.litellm_url == "http://litellm:4000"
        assert config.litellm_key == "sk-litellm-key"
        assert config.database_url == "postgresql://u:p@host:5432/db"
        assert config.routing.quality_weight == 0.7
        assert config.routing.cost_weight == 0.3
        assert config.sessions.max_messages == 50
        assert config.sessions.ttl_seconds == 7200
        assert config.security.warden_enabled is False

    def test_empty_yaml_returns_defaults(self, tmp_path: Path) -> None:
        """An empty YAML file yields default config."""
        f = tmp_path / "empty.yaml"
        f.write_text("")
        config = load_config(f)

        assert config.routing.quality_weight == 0.6
        assert config.sessions.max_messages == 20
        assert config.litellm_url == "http://litellm:4000"

    def test_invalid_yaml_raises_value_error(self, tmp_path: Path) -> None:
        """Malformed YAML raises ValueError with the path in the message."""
        f = tmp_path / "broken.yaml"
        f.write_text("{ invalid: yaml: [unclosed")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_config(f)

    def test_nonexistent_path_returns_defaults(self) -> None:
        """A path that does not exist falls through to defaults (no crash)."""
        config = load_config("/tmp/does_not_exist_stronghold_test.yaml")
        assert isinstance(config, StrongholdConfig)
        assert config.routing.quality_weight == 0.6


class TestLoadConfigEnvOverrides:
    """Environment variables override YAML values."""

    def test_database_url_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABASE_URL env overrides yaml database_url."""
        f = tmp_path / "cfg.yaml"
        f.write_text("database_url: from-yaml\n")
        monkeypatch.setenv("DATABASE_URL", "postgresql://env:env@host:5432/db")
        config = load_config(f)
        assert config.database_url == "postgresql://env:env@host:5432/db"

    def test_litellm_url_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """LITELLM_URL env overrides yaml litellm_url."""
        f = tmp_path / "cfg.yaml"
        f.write_text("litellm_url: http://from-yaml:4000\n")
        monkeypatch.setenv("LITELLM_URL", "http://from-env:9999")
        config = load_config(f)
        assert config.litellm_url == "http://from-env:9999"

    def test_litellm_master_key_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LITELLM_MASTER_KEY maps to litellm_key."""
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-override")
        config = load_config("/tmp/no_file_here.yaml")
        assert config.litellm_key == "sk-master-override"

    def test_router_api_key_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ROUTER_API_KEY env overrides yaml router_api_key."""
        monkeypatch.setenv("ROUTER_API_KEY", "sk-router-key-that-is-at-least-32chars-long!")
        config = load_config("/tmp/no_file.yaml")
        assert config.router_api_key == "sk-router-key-that-is-at-least-32chars-long!"

    def test_phoenix_endpoint_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PHOENIX_COLLECTOR_ENDPOINT env overrides yaml phoenix_endpoint."""
        monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://phoenix:6006")
        config = load_config("/tmp/no_file.yaml")
        assert config.phoenix_endpoint == "http://phoenix:6006"

    def test_env_overrides_take_precedence_over_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both YAML and env set a value, env wins."""
        f = tmp_path / "cfg.yaml"
        f.write_text("litellm_key: yaml-key\nrouter_api_key: yaml-router\n")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "env-key")
        monkeypatch.setenv(
            "ROUTER_API_KEY",
            "env-router-key-long-enough-for-32-chars!!",
        )
        config = load_config(f)
        assert config.litellm_key == "env-key"
        assert config.router_api_key == "env-router-key-long-enough-for-32-chars!!"


class TestDefaultValues:
    """StrongholdConfig and sub-model defaults match expected values."""

    def test_routing_defaults(self) -> None:
        cfg = RoutingConfig()
        assert cfg.quality_weight == 0.6
        assert cfg.cost_weight == 0.4
        assert cfg.reserve_pct == 0.05
        assert cfg.priority_multipliers == {
            "low": 0.8,
            "normal": 1.0,
            "high": 1.2,
            "critical": 1.5,
        }

    def test_sessions_defaults(self) -> None:
        cfg = SessionsConfig()
        assert cfg.max_messages == 20
        assert cfg.ttl_seconds == 86400

    def test_security_defaults(self) -> None:
        cfg = SecurityConfig()
        assert cfg.warden_enabled is True
        assert cfg.sentinel_enabled is True
        assert cfg.gate_query_improve is True
        assert cfg.gate_model == "auto"

    def test_cors_defaults(self) -> None:
        cfg = CORSConfig()
        assert cfg.allowed_origins == ["http://localhost:3200"]
        assert "GET" in cfg.allowed_methods
        assert "Authorization" in cfg.allowed_headers
        assert cfg.allow_credentials is True

    def test_rate_limit_defaults(self) -> None:
        cfg = RateLimitConfig()
        assert cfg.requests_per_minute == 300
        assert cfg.burst_limit == 50
        assert cfg.enabled is True

    def test_stronghold_config_defaults(self) -> None:
        cfg = StrongholdConfig()
        assert cfg.litellm_url == "http://litellm:4000"
        assert cfg.max_request_body_bytes == 1_048_576
        assert cfg.providers == {}
        assert cfg.models == {}
        assert cfg.task_types == {}
        assert cfg.database_url == ""
        assert cfg.webhook_secret == ""


class TestPrivateIPBlocking:
    """_validate_url_not_private rejects non-HTTPS and private/loopback IPs."""

    def test_http_scheme_rejected(self) -> None:
        """Plain HTTP URLs are rejected."""
        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_url_not_private("http://example.com/path", "test_field")

    def test_no_hostname_rejected(self) -> None:
        """URLs without a hostname are rejected."""
        with pytest.raises(ValueError, match="has no hostname"):
            _validate_url_not_private("https:///path", "test_field")

    def test_loopback_rejected(self) -> None:
        """localhost (127.0.0.1) is rejected as private."""
        with pytest.raises(ValueError, match="private/loopback"):
            _validate_url_not_private("https://127.0.0.1/jwks", "test_field")

    def test_private_ip_rejected(self) -> None:
        """RFC 1918 private IPs (e.g. 10.0.0.1) are rejected."""
        with pytest.raises(ValueError, match="private/loopback"):
            _validate_url_not_private("https://10.0.0.1/jwks", "test_field")

    def test_unresolvable_hostname_warns_but_passes(self) -> None:
        """DNS failures are warned but allowed (scheme check is the hard gate)."""
        # This hostname cannot resolve, so the function should log a warning
        # but not raise.
        _validate_url_not_private(
            "https://unresolvable-host-abc123xyz.example.invalid/path",
            "test_field",
        )


class TestCORSValidation:
    """CORS origin validation in load_config."""

    def test_wildcard_origin_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CORS_ORIGINS containing '*' is rejected."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "*")
        with pytest.raises(ValueError, match="must not contain"):
            load_config("/tmp/no_file.yaml")

    def test_javascript_uri_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """javascript: URIs in CORS_ORIGINS are rejected."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "javascript:alert(1)")
        with pytest.raises(ValueError, match="unsafe origin"):
            load_config("/tmp/no_file.yaml")

    def test_data_uri_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """data: URIs in CORS_ORIGINS are rejected."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "data:text/html,<h1>hi</h1>")
        with pytest.raises(ValueError, match="unsafe origin"):
            load_config("/tmp/no_file.yaml")

    def test_multiple_valid_origins_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Comma-separated HTTPS origins are accepted and trimmed."""
        monkeypatch.setenv(
            "STRONGHOLD_CORS_ORIGINS",
            "https://app.example.com, https://admin.example.com",
        )
        config = load_config("/tmp/no_file.yaml")
        assert config.cors.allowed_origins == [
            "https://app.example.com",
            "https://admin.example.com",
        ]

    def test_localhost_http_origin_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """http://localhost origins are accepted (dev convenience)."""
        monkeypatch.setenv("STRONGHOLD_CORS_ORIGINS", "http://localhost:3000")
        config = load_config("/tmp/no_file.yaml")
        assert config.cors.allowed_origins == ["http://localhost:3000"]


class TestSecretLengthEnforcement:
    """Minimum lengths for secrets are enforced at load time."""

    def test_short_webhook_secret_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_WEBHOOK_SECRET shorter than 16 chars raises ValueError."""
        monkeypatch.setenv("STRONGHOLD_WEBHOOK_SECRET", "tooshort")
        with pytest.raises(ValueError, match="at least 16 characters"):
            load_config("/tmp/no_file.yaml")

    def test_valid_webhook_secret_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_WEBHOOK_SECRET >= 16 chars is accepted."""
        monkeypatch.setenv("STRONGHOLD_WEBHOOK_SECRET", "a-valid-secret-that-is-long-enough")
        config = load_config("/tmp/no_file.yaml")
        assert config.webhook_secret == "a-valid-secret-that-is-long-enough"


class TestNestedAuthOverrides:
    """Auth-related env vars populate the nested auth config."""

    def test_jwks_url_requires_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_JWKS_URL with http:// scheme is rejected."""
        monkeypatch.setenv("STRONGHOLD_JWKS_URL", "http://sso.example.com/jwks")
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/tmp/no_file.yaml")

    def test_auth_issuer_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_ISSUER populates auth.issuer (needs HTTPS).

        Uses an unresolvable .invalid TLD so DNS lookup triggers a gaierror,
        which the loader treats as a non-fatal warning (scheme check is the
        hard gate).
        """
        monkeypatch.setenv(
            "STRONGHOLD_AUTH_ISSUER",
            "https://unresolvable-issuer-xyz.invalid",
        )
        config = load_config("/tmp/no_file.yaml")
        assert config.auth.issuer == "https://unresolvable-issuer-xyz.invalid"

    def test_auth_audience_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_AUDIENCE populates auth.audience."""
        monkeypatch.setenv("STRONGHOLD_AUTH_AUDIENCE", "api://stronghold")
        config = load_config("/tmp/no_file.yaml")
        assert config.auth.audience == "api://stronghold"

    def test_auth_client_id_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_CLIENT_ID populates auth.client_id."""
        monkeypatch.setenv("STRONGHOLD_AUTH_CLIENT_ID", "my-client-id")
        config = load_config("/tmp/no_file.yaml")
        assert config.auth.client_id == "my-client-id"

    def test_auth_authorization_url_requires_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_AUTHORIZATION_URL with http:// is rejected."""
        monkeypatch.setenv(
            "STRONGHOLD_AUTH_AUTHORIZATION_URL",
            "http://auth.example.com/authorize",
        )
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/tmp/no_file.yaml")

    def test_auth_token_url_requires_https(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_TOKEN_URL with http:// is rejected."""
        monkeypatch.setenv(
            "STRONGHOLD_AUTH_TOKEN_URL",
            "http://auth.example.com/token",
        )
        with pytest.raises(ValueError, match="must use HTTPS"):
            load_config("/tmp/no_file.yaml")

    def test_auth_client_secret_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_AUTH_CLIENT_SECRET populates auth.client_secret."""
        monkeypatch.setenv("STRONGHOLD_AUTH_CLIENT_SECRET", "super-secret-value")
        config = load_config("/tmp/no_file.yaml")
        assert config.auth.client_secret == "super-secret-value"


class TestRateLimitAndBodyOverrides:
    """Rate limit RPM and max body size env overrides."""

    def test_rate_limit_rpm_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_RATE_LIMIT_RPM sets requests_per_minute."""
        monkeypatch.setenv("STRONGHOLD_RATE_LIMIT_RPM", "60")
        config = load_config("/tmp/no_file.yaml")
        assert config.rate_limit.requests_per_minute == 60

    def test_max_body_bytes_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """STRONGHOLD_MAX_REQUEST_BODY_BYTES sets max_request_body_bytes."""
        monkeypatch.setenv("STRONGHOLD_MAX_REQUEST_BODY_BYTES", "524288")
        config = load_config("/tmp/no_file.yaml")
        assert config.max_request_body_bytes == 524288


class TestConfigPathResolution:
    """Config path resolution: explicit path, env var, default."""

    def test_explicit_path_used(self, tmp_path: Path) -> None:
        """An explicit path argument is used regardless of env."""
        f = tmp_path / "explicit.yaml"
        f.write_text("router_api_key: from-explicit\n")
        config = load_config(f)
        assert config.router_api_key == "from-explicit"

    def test_stronghold_config_env_used_when_no_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STRONGHOLD_CONFIG env var is used when no explicit path given."""
        f = tmp_path / "env_config.yaml"
        f.write_text("router_api_key: from-env-config\n")
        monkeypatch.setenv("STRONGHOLD_CONFIG", str(f))
        config = load_config()
        assert config.router_api_key == "from-env-config"

    def test_string_path_accepted(self, tmp_path: Path) -> None:
        """load_config accepts a plain string path (not just Path objects)."""
        f = tmp_path / "str_path.yaml"
        f.write_text("litellm_key: str-key\n")
        config = load_config(str(f))
        assert config.litellm_key == "str-key"
