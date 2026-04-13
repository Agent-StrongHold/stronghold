"""Tests for configuration validation."""

import pytest

from stronghold.types.config import RoutingConfig, StrongholdConfig, TaskTypeConfig


class TestConfigValidation:
    def test_default_config_is_valid(self) -> None:
        config = StrongholdConfig()
        assert config.routing.quality_weight == 0.6
        assert config.routing.cost_weight == 0.4

    def test_custom_routing_config(self) -> None:
        config = StrongholdConfig(routing=RoutingConfig(quality_weight=0.8, cost_weight=0.2))
        assert config.routing.quality_weight == 0.8

    def test_task_types_parsed(self) -> None:
        config = StrongholdConfig(
            task_types={"code": TaskTypeConfig(keywords=["code"], min_tier="medium")},
        )
        assert "code" in config.task_types
        assert config.task_types["code"].min_tier == "medium"

    def test_empty_providers(self) -> None:
        config = StrongholdConfig(providers={})
        assert len(config.providers) == 0

    def test_permissions_parsed(self) -> None:
        config = StrongholdConfig(permissions={"admin": ["*"], "viewer": ["search"]})
        assert config.permissions["admin"] == ["*"]


class TestRoutingConfig:
    def test_defaults(self) -> None:
        rc = RoutingConfig()
        assert rc.reserve_pct == 0.05
        assert "P2" in rc.priority_multipliers

    def test_custom_multipliers(self) -> None:
        rc = RoutingConfig(priority_multipliers={"P4": 0.5, "P0": 2.0})
        assert rc.priority_multipliers["P4"] == 0.5



class TestCorsSecurityValidation:
    """CORS origin validation rejects dangerous patterns."""

    def test_cors_wildcard_rejected(self, monkeypatch: object) -> None:
        """CORS_ORIGINS='*' must raise ValueError."""

        from stronghold.config.loader import load_config

        # Use a pytest monkeypatch to set env var

        mp = pytest.MonkeyPatch()
        mp.setenv("STRONGHOLD_CORS_ORIGINS", "*")
        mp.setenv("STRONGHOLD_CONFIG", "/dev/null")
        try:
            with pytest.raises(ValueError, match="must not contain"):
                load_config()
        finally:
            mp.undo()

    def test_cors_javascript_scheme_rejected(self) -> None:
        """CORS_ORIGINS='javascript:alert(1)' must raise ValueError."""

        from stronghold.config.loader import load_config

        mp = pytest.MonkeyPatch()
        mp.setenv("STRONGHOLD_CORS_ORIGINS", "javascript:alert(1)")
        mp.setenv("STRONGHOLD_CONFIG", "/dev/null")
        try:
            with pytest.raises(ValueError, match="unsafe origin"):
                load_config()
        finally:
            mp.undo()


class TestJwksUrlValidation:
    """JWKS URL must use HTTPS scheme."""

    def test_jwks_url_requires_https(self) -> None:
        """STRONGHOLD_JWKS_URL='http://evil.com' must raise ValueError."""

        from stronghold.config.loader import load_config

        mp = pytest.MonkeyPatch()
        mp.setenv("STRONGHOLD_JWKS_URL", "http://evil.com/.well-known/jwks.json")
        mp.setenv("STRONGHOLD_CONFIG", "/dev/null")
        try:
            with pytest.raises(ValueError, match="must use HTTPS"):
                load_config()
        finally:
            mp.undo()


class TestWebhookSecretValidation:
    """Webhook secret must meet minimum length requirement."""

    def test_webhook_secret_minimum_length(self) -> None:
        """Short webhook secret (< 16 chars) must raise ValueError."""

        from stronghold.config.loader import load_config

        mp = pytest.MonkeyPatch()
        mp.setenv("STRONGHOLD_WEBHOOK_SECRET", "short")
        mp.setenv("STRONGHOLD_CONFIG", "/dev/null")
        try:
            with pytest.raises(ValueError, match="at least 16 characters"):
                load_config()
        finally:
            mp.undo()
