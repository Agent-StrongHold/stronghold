"""Tests for config validation CLI and validate_config function."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.config.validator import ConfigValidationError, validate_config

if TYPE_CHECKING:
    import pathlib


class TestValidateConfigValidFile:
    """Valid configs should return no errors."""

    def test_example_config_is_valid(self) -> None:
        """The shipped example.yaml must validate without errors."""
        errors = validate_config("config/example.yaml")
        error_msgs = [e for e in errors if e.severity == "error"]
        assert error_msgs == []

    def test_minimal_valid_config(self, tmp_path: pathlib.Path) -> None:
        """A config with only defaults should validate cleanly."""
        cfg = tmp_path / "minimal.yaml"
        cfg.write_text("{}\n")
        errors = validate_config(str(cfg))
        error_msgs = [e for e in errors if e.severity == "error"]
        assert error_msgs == []


class TestValidateConfigMissingFile:
    """Missing or unparseable files should produce errors."""

    def test_nonexistent_file_returns_error(self) -> None:
        errors = validate_config("/nonexistent/config.yaml")
        assert len(errors) == 1
        assert errors[0].severity == "error"
        msg = errors[0].message.lower()
        assert "not found" in msg or "does not exist" in msg

    def test_invalid_yaml_returns_error(self, tmp_path: pathlib.Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("{ invalid: yaml: [")
        errors = validate_config(str(bad))
        assert any(e.severity == "error" and "yaml" in e.message.lower() for e in errors)


class TestValidateConfigURLFormats:
    """URL fields must have valid format."""

    def test_litellm_url_invalid_scheme(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("litellm_url: not-a-url\n")
        errors = validate_config(str(cfg))
        assert any(e.field == "litellm_url" and e.severity == "error" for e in errors)

    def test_litellm_url_valid_http(self, tmp_path: pathlib.Path) -> None:
        """http is allowed for internal service URLs (litellm, phoenix, etc.)."""
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("litellm_url: http://litellm:4000\n")
        errors = validate_config(str(cfg))
        url_errors = [e for e in errors if e.field == "litellm_url" and e.severity == "error"]
        assert url_errors == []

    def test_phoenix_endpoint_invalid(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("phoenix_endpoint: ://broken\n")
        errors = validate_config(str(cfg))
        assert any(e.field == "phoenix_endpoint" and e.severity == "error" for e in errors)


class TestValidateConfigPrivateIPs:
    """Public-facing URLs must not contain private IPs."""

    def test_auth_jwks_url_private_ip_warning(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("auth:\n  jwks_url: https://192.168.1.1/.well-known/jwks.json\n")
        errors = validate_config(str(cfg))
        assert any(e.field == "auth.jwks_url" and "private" in e.message.lower() for e in errors)

    def test_auth_jwks_url_loopback_warning(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("auth:\n  jwks_url: https://127.0.0.1/.well-known/jwks.json\n")
        errors = validate_config(str(cfg))
        assert any(
            e.field == "auth.jwks_url"
            and ("private" in e.message.lower() or "loopback" in e.message.lower())
            for e in errors
        )


class TestValidateConfigProviders:
    """Provider configs must have required fields."""

    def test_provider_missing_status(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("providers:\n  bad_provider:\n    billing_cycle: monthly\n")
        errors = validate_config(str(cfg))
        assert any(
            e.field.startswith("providers.bad_provider") and e.severity == "error" for e in errors
        )

    def test_provider_valid(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "providers:\n"
            "  good:\n"
            "    status: active\n"
            "    billing_cycle: monthly\n"
            "    free_tokens: 1000\n"
        )
        errors = validate_config(str(cfg))
        provider_errors = [
            e for e in errors if e.field.startswith("providers.") and e.severity == "error"
        ]
        assert provider_errors == []


class TestValidateConfigModels:
    """Model configs must have required fields."""

    def test_model_missing_provider(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text("models:\n  bad-model:\n    tier: small\n    quality: 0.5\n")
        errors = validate_config(str(cfg))
        assert any(e.field.startswith("models.bad-model") and e.severity == "error" for e in errors)

    def test_model_invalid_tier(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "models:\n"
            "  bad-model:\n"
            "    provider: test\n"
            "    tier: gigantic\n"
            "    quality: 0.5\n"
            "    speed: 100\n"
            "    litellm_id: test/bad\n"
            "    strengths: [chat]\n"
        )
        errors = validate_config(str(cfg))
        assert any(
            e.field.startswith("models.bad-model") and "tier" in e.message.lower() for e in errors
        )

    def test_model_quality_out_of_range(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "models:\n"
            "  bad-model:\n"
            "    provider: test\n"
            "    tier: small\n"
            "    quality: 5.0\n"
            "    speed: 100\n"
            "    litellm_id: test/bad\n"
            "    strengths: [chat]\n"
        )
        errors = validate_config(str(cfg))
        assert any(
            e.field.startswith("models.bad-model") and "quality" in e.message.lower()
            for e in errors
        )

    def test_model_valid(self, tmp_path: pathlib.Path) -> None:
        cfg = tmp_path / "cfg.yaml"
        cfg.write_text(
            "providers:\n"
            "  test:\n"
            "    status: active\n"
            "    billing_cycle: monthly\n"
            "    free_tokens: 1000\n"
            "models:\n"
            "  good-model:\n"
            "    provider: test\n"
            "    tier: small\n"
            "    quality: 0.5\n"
            "    speed: 100\n"
            "    litellm_id: test/good\n"
            "    strengths: [chat]\n"
        )
        errors = validate_config(str(cfg))
        model_errors = [
            e for e in errors if e.field.startswith("models.") and e.severity == "error"
        ]
        assert model_errors == []


class TestConfigValidationErrorDataclass:
    """ConfigValidationError should be a proper dataclass."""

    def test_fields(self) -> None:
        err = ConfigValidationError(
            field="litellm_url",
            message="Invalid URL",
            severity="error",
        )
        assert err.field == "litellm_url"
        assert err.message == "Invalid URL"
        assert err.severity == "error"

    def test_warning_severity(self) -> None:
        err = ConfigValidationError(
            field="auth.jwks_url",
            message="Private IP detected",
            severity="warning",
        )
        assert err.severity == "warning"


class TestValidateConfigCLI:
    """The module can be invoked as python -m stronghold.config.validator."""

    def test_cli_valid_config(self, tmp_path: pathlib.Path) -> None:
        import subprocess
        import sys

        cfg = tmp_path / "valid.yaml"
        cfg.write_text("{}\n")
        result = subprocess.run(
            [sys.executable, "-m", "stronghold.config.validator", str(cfg)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "valid" in result.stdout.lower() or "0 error" in result.stdout.lower()

    def test_cli_invalid_config(self, tmp_path: pathlib.Path) -> None:
        import subprocess
        import sys

        cfg = tmp_path / "bad.yaml"
        cfg.write_text("litellm_url: not-a-url\n")
        result = subprocess.run(
            [sys.executable, "-m", "stronghold.config.validator", str(cfg)],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_cli_missing_file(self) -> None:
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "stronghold.config.validator", "/no/such/file.yaml"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
