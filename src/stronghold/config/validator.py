"""Config validation: load YAML, check against StrongholdConfig schema, report errors.

Usage as CLI::

    python -m stronghold.config.validator config/example.yaml
"""

from __future__ import annotations

import ipaddress
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml

from stronghold.types.config import StrongholdConfig

_VALID_TIERS = {"small", "medium", "large"}

_REQUIRED_PROVIDER_FIELDS = {"status"}
_REQUIRED_MODEL_FIELDS = {"provider", "tier", "quality", "speed", "litellm_id", "strengths"}

# URL fields that must be syntactically valid when non-empty.
# Tuple of (field_name, allow_http).  Internal services allow http.
_URL_FIELDS: list[tuple[str, bool]] = [
    ("litellm_url", True),
    ("phoenix_endpoint", True),
    ("database_url", True),
    ("redis_url", True),
]

# Auth URL fields that should not point at private IPs.
_AUTH_PUBLIC_URL_FIELDS = [
    "jwks_url",
    "issuer",
    "authorization_url",
    "token_url",
]


@dataclass(frozen=True)
class ConfigValidationError:
    """A single validation finding."""

    field: str
    message: str
    severity: Literal["error", "warning"]


def _validate_url_syntax(
    value: str,
    field: str,
    allow_http: bool,
) -> list[ConfigValidationError]:
    """Check that *value* is a syntactically valid URL."""
    errors: list[ConfigValidationError] = []
    parsed = urlparse(value)
    valid_schemes = {"http", "https"} if allow_http else {"https"}
    # Also accept postgres/redis schemes for DB/cache URLs
    if field in ("database_url", "redis_url"):
        valid_schemes |= {"postgresql", "postgres", "redis", "rediss"}
    if parsed.scheme not in valid_schemes:
        errors.append(
            ConfigValidationError(
                field=field,
                message=(
                    f"Invalid URL scheme {parsed.scheme!r} in {value!r}; "
                    f"expected one of {sorted(valid_schemes)}"
                ),
                severity="error",
            )
        )
    if not parsed.hostname:
        errors.append(
            ConfigValidationError(
                field=field,
                message=f"URL has no hostname: {value!r}",
                severity="error",
            )
        )
    return errors


def _check_private_ip(hostname: str) -> bool:
    """Return True if *hostname* is a literal private/loopback/link-local IP."""
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)


def validate_config(config_path: str) -> list[ConfigValidationError]:
    """Load a YAML config file and validate it against the StrongholdConfig schema.

    Returns a list of :class:`ConfigValidationError` instances.
    An empty list means the config is valid.
    """
    errors: list[ConfigValidationError] = []
    path = Path(config_path)

    # ── File existence ──────────────────────────────────────────────
    if not path.exists():
        return [
            ConfigValidationError(
                field="config_path",
                message=f"Config file does not exist: {config_path}",
                severity="error",
            )
        ]

    # ── YAML parsing ────────────────────────────────────────────────
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        return [
            ConfigValidationError(
                field="config_path",
                message=f"Invalid YAML: {exc}",
                severity="error",
            )
        ]

    # ── Pydantic schema validation ──────────────────────────────────
    try:
        config = StrongholdConfig(**raw)
    except Exception as exc:  # noqa: BLE001
        return [
            ConfigValidationError(
                field="schema",
                message=f"Schema validation failed: {exc}",
                severity="error",
            )
        ]

    # ── URL format checks ───────────────────────────────────────────
    for field_name, allow_http in _URL_FIELDS:
        value = getattr(config, field_name, "")
        if value:
            errors.extend(_validate_url_syntax(value, field_name, allow_http))

    # ── Auth public URL checks (no private IPs) ────────────────────
    for auth_field in _AUTH_PUBLIC_URL_FIELDS:
        value = getattr(config.auth, auth_field, "")
        if not value:
            continue
        full_field = f"auth.{auth_field}"
        parsed = urlparse(value)
        hostname = parsed.hostname or ""
        if _check_private_ip(hostname):
            errors.append(
                ConfigValidationError(
                    field=full_field,
                    message=f"Private/loopback IP in public URL: {value!r}",
                    severity="warning",
                )
            )
        # Also validate scheme
        if parsed.scheme not in ("http", "https"):
            errors.append(
                ConfigValidationError(
                    field=full_field,
                    message=f"Invalid URL scheme {parsed.scheme!r} in {value!r}",
                    severity="error",
                )
            )

    # ── Provider validation ─────────────────────────────────────────
    for name, provider_cfg in config.providers.items():
        provider_dict = dict(provider_cfg) if isinstance(provider_cfg, dict) else {}
        for req_field in _REQUIRED_PROVIDER_FIELDS:
            if req_field not in provider_dict:
                errors.append(
                    ConfigValidationError(
                        field=f"providers.{name}",
                        message=f"Missing required field {req_field!r}",
                        severity="error",
                    )
                )

    # ── Model validation ────────────────────────────────────────────
    for name, model_cfg in config.models.items():
        model_dict = dict(model_cfg) if isinstance(model_cfg, dict) else {}
        prefix = f"models.{name}"

        for req_field in _REQUIRED_MODEL_FIELDS:
            if req_field not in model_dict:
                errors.append(
                    ConfigValidationError(
                        field=prefix,
                        message=f"Missing required field {req_field!r}",
                        severity="error",
                    )
                )

        tier = model_dict.get("tier")
        if tier is not None and tier not in _VALID_TIERS:
            errors.append(
                ConfigValidationError(
                    field=prefix,
                    message=f"Invalid tier {tier!r}; must be one of {sorted(_VALID_TIERS)}",
                    severity="error",
                )
            )

        quality = model_dict.get("quality")
        if quality is not None:
            try:
                q = float(str(quality))
                if not (0.0 <= q <= 1.0):
                    errors.append(
                        ConfigValidationError(
                            field=prefix,
                            message=f"Quality {q} out of range [0.0, 1.0]",
                            severity="error",
                        )
                    )
            except (TypeError, ValueError):
                errors.append(
                    ConfigValidationError(
                        field=prefix,
                        message=f"Quality must be a number, got {quality!r}",
                        severity="error",
                    )
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for config validation."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: python -m stronghold.config.validator <config.yaml>", file=sys.stderr)
        return 2

    config_path = args[0]
    results = validate_config(config_path)

    error_count = sum(1 for e in results if e.severity == "error")
    warning_count = sum(1 for e in results if e.severity == "warning")

    for err in results:
        tag = "ERROR" if err.severity == "error" else "WARNING"
        print(f"[{tag}] {err.field}: {err.message}")

    if error_count == 0 and warning_count == 0:
        print(f"Config {config_path} is valid. 0 errors, 0 warnings.")
    else:
        print(f"\n{error_count} error(s), {warning_count} warning(s).")

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
