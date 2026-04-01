"""Tests for K8s secrets manager integration with env var fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.config.secrets import SecretResolver

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestResolvePassthrough:
    """Values without the ${secret:...} pattern pass through unchanged."""

    def test_plain_string_returned_as_is(self) -> None:
        resolver = SecretResolver()
        assert resolver.resolve("hello-world") == "hello-world"

    def test_empty_string_returned_as_is(self) -> None:
        resolver = SecretResolver()
        assert resolver.resolve("") == ""

    def test_partial_pattern_not_resolved(self) -> None:
        resolver = SecretResolver()
        assert resolver.resolve("${secret:") == "${secret:"

    def test_url_without_secret_pattern(self) -> None:
        resolver = SecretResolver()
        assert resolver.resolve("https://example.com") == "https://example.com"


class TestResolveK8s:
    """K8s mounted file resolution via ${secret:k8s/namespace/name}."""

    def test_resolve_from_k8s_mount(self, tmp_path: Path) -> None:
        """Reads secret from mounted file at /var/run/secrets/{path}."""
        secret_dir = tmp_path / "k8s" / "stronghold-secrets"
        secret_dir.mkdir(parents=True)
        secret_file = secret_dir / "jwt-signing-key"
        secret_file.write_text("super-secret-jwt-key-12345")

        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/stronghold-secrets/jwt-signing-key}")
        assert result == "super-secret-jwt-key-12345"

    def test_k8s_file_with_trailing_newline_stripped(self, tmp_path: Path) -> None:
        """Trailing whitespace/newlines in secret files are stripped."""
        secret_dir = tmp_path / "k8s" / "my-namespace"
        secret_dir.mkdir(parents=True)
        secret_file = secret_dir / "db-password"
        secret_file.write_text("p@ssw0rd\n")

        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/my-namespace/db-password}")
        assert result == "p@ssw0rd"

    def test_k8s_nested_path(self, tmp_path: Path) -> None:
        """Supports multi-level paths under secrets root."""
        secret_dir = tmp_path / "k8s" / "team-a" / "prod"
        secret_dir.mkdir(parents=True)
        (secret_dir / "api-key").write_text("key-abc-123")

        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/team-a/prod/api-key}")
        assert result == "key-abc-123"


class TestResolveEnvFallback:
    """When K8s mount is missing, fall back to environment variable."""

    def test_env_fallback_when_k8s_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If K8s path doesn't exist, tries env var (uppercased, hyphens to underscores)."""
        monkeypatch.setenv("JWT_SIGNING_KEY", "env-fallback-key")
        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/stronghold-secrets/jwt-signing-key}")
        assert result == "env-fallback-key"

    def test_env_name_derived_from_last_path_segment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Env var name: uppercased, hyphens to underscores from last path segment."""
        monkeypatch.setenv("DB_PASSWORD", "from-env")
        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/namespace/db-password}")
        assert result == "from-env"

    def test_no_k8s_no_env_returns_empty_string(self, tmp_path: Path) -> None:
        """When neither K8s mount nor env var exists, returns empty string."""
        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/namespace/nonexistent-secret}")
        assert result == ""

    def test_k8s_takes_precedence_over_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """K8s mounted file wins even when env var is also set."""
        secret_dir = tmp_path / "k8s" / "ns"
        secret_dir.mkdir(parents=True)
        (secret_dir / "api-key").write_text("from-k8s")
        monkeypatch.setenv("API_KEY", "from-env")

        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/ns/api-key}")
        assert result == "from-k8s"


class TestResolveConfig:
    """Recursive resolution of all string values in a config dict."""

    def test_flat_dict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_PASSWORD", "s3cret")
        resolver = SecretResolver(secrets_root=tmp_path)
        config = {
            "host": "localhost",
            "password": "${secret:k8s/ns/db-password}",
        }
        resolved = resolver.resolve_config(config)
        assert resolved == {"host": "localhost", "password": "s3cret"}

    def test_nested_dict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JWT_KEY", "jwt-value")
        resolver = SecretResolver(secrets_root=tmp_path)
        config = {
            "auth": {
                "token": "${secret:k8s/ns/jwt-key}",
                "issuer": "https://sso.example.com",
            },
        }
        resolved = resolver.resolve_config(config)
        assert resolved["auth"]["token"] == "jwt-value"
        assert resolved["auth"]["issuer"] == "https://sso.example.com"

    def test_list_values_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_A", "val-a")
        monkeypatch.setenv("SECRET_B", "val-b")
        resolver = SecretResolver(secrets_root=tmp_path)
        config = {
            "keys": ["${secret:k8s/ns/secret-a}", "${secret:k8s/ns/secret-b}", "plain"],
        }
        resolved = resolver.resolve_config(config)
        assert resolved["keys"] == ["val-a", "val-b", "plain"]

    def test_non_string_values_unchanged(self, tmp_path: Path) -> None:
        resolver = SecretResolver(secrets_root=tmp_path)
        config: dict[str, object] = {
            "port": 5432,
            "enabled": True,
            "ratio": 0.5,
            "nothing": None,
        }
        resolved = resolver.resolve_config(config)
        assert resolved == config

    def test_original_dict_not_mutated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MY_SECRET", "resolved")
        resolver = SecretResolver(secrets_root=tmp_path)
        config = {"key": "${secret:k8s/ns/my-secret}"}
        resolver.resolve_config(config)
        assert config["key"] == "${secret:k8s/ns/my-secret}"


class TestPathTraversal:
    """Secret paths must not escape the secrets root."""

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Paths with '..' that escape the root are rejected."""
        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:k8s/../../../etc/passwd}")
        assert result == ""

    def test_absolute_path_in_pattern_blocked(self, tmp_path: Path) -> None:
        """Absolute paths inside the pattern are rejected."""
        resolver = SecretResolver(secrets_root=tmp_path)
        result = resolver.resolve("${secret:/etc/passwd}")
        assert result == ""
