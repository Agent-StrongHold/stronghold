"""K8s secrets manager integration with environment variable fallback.

Resolves ``${secret:path/name}`` references in config values by reading
mounted Kubernetes secret files, falling back to environment variables
when the file does not exist (dev/CI convenience).

Pattern example::

    ${secret:k8s/stronghold-secrets/jwt-signing-key}
    → reads /var/run/secrets/k8s/stronghold-secrets/jwt-signing-key
    → fallback: env var JWT_SIGNING_KEY  (uppercased, hyphens → underscores)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(r"^\$\{secret:(.+)\}$")

_DEFAULT_SECRETS_ROOT = Path("/var/run/secrets")


class SecretResolver:
    """Resolve ``${secret:...}`` references from K8s mounts or env vars.

    Args:
        secrets_root: Base directory for mounted secrets.
            Defaults to ``/var/run/secrets``.  Override in tests via ``tmp_path``.
    """

    def __init__(self, secrets_root: Path | None = None) -> None:
        self._root = secrets_root or _DEFAULT_SECRETS_ROOT

    # ── Public API ──────────────────────────────────────────────────────

    def resolve(self, value: str) -> str:
        """Resolve a single value.

        If *value* matches ``${secret:path/name}``, attempt resolution from
        the K8s mount first, then fall back to an environment variable.
        Otherwise return *value* unchanged.
        """
        match = _SECRET_PATTERN.match(value)
        if match is None:
            return value

        secret_path = match.group(1)

        # Block absolute paths inside the pattern
        if secret_path.startswith("/"):
            logger.warning("Absolute path in secret reference rejected: %s", value)
            return ""

        # Resolve and validate the full filesystem path
        full_path = (self._root / secret_path).resolve()
        if not str(full_path).startswith(str(self._root.resolve())):
            logger.warning("Path traversal in secret reference rejected: %s", value)
            return ""

        # Derive the env-var name from the last path segment
        name = secret_path.rsplit("/", 1)[-1]

        # Try K8s mount first
        k8s_value = self._resolve_k8s(full_path)
        if k8s_value is not None:
            return k8s_value

        # Fallback: environment variable
        env_value = self._resolve_env(name)
        if env_value is not None:
            return env_value

        logger.warning("Secret not found (no K8s mount, no env var): %s", value)
        return ""

    def resolve_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Recursively resolve all string values in a config dict.

        Returns a **new** dict; the original is not mutated.
        """
        result: dict[str, Any] = self._walk(config)
        return result

    # ── Private helpers ─────────────────────────────────────────────────

    def _resolve_k8s(self, path: Path) -> str | None:
        """Read a secret from a K8s-mounted file, or *None* if missing."""
        if path.is_file():
            return path.read_text().strip()
        return None

    def _resolve_env(self, name: str) -> str | None:
        """Read a secret from an environment variable, or *None* if unset.

        The env-var name is derived from *name* by uppercasing and replacing
        hyphens with underscores (e.g. ``jwt-signing-key`` → ``JWT_SIGNING_KEY``).
        """
        env_name = name.upper().replace("-", "_")
        return os.environ.get(env_name)

    def _walk(self, obj: Any) -> Any:
        """Recursively walk a nested structure, resolving string values."""
        if isinstance(obj, dict):
            return {k: self._walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._walk(item) for item in obj]
        if isinstance(obj, str):
            return self.resolve(obj)
        return obj
