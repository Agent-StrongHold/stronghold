"""RuntimeConfig: CLI flags → env vars → YAML → defaults.

Pydantic-free. Stdlib dataclass + manual validation. Keeps deps minimal.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RuntimeConfig:
    # Reactor
    tick_rate_hz: int = 100
    executor_workers: int = 8

    # Storage
    db_path: str = ":memory:"

    # Logging / observability
    log_level: str = "INFO"
    log_format: str = "plain"               # "plain" | "json"
    metrics_port: int | None = None

    # Providers
    provider_choice: tuple[str, ...] = ("fake",)
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    zai_api_key: str | None = None

    # Workload (chunk 3)
    scenario: str | None = None

    # Self identity
    self_label: str = "default"

    def validate(self) -> None:
        if self.tick_rate_hz <= 0:
            raise ValueError("tick_rate_hz must be positive")
        if self.executor_workers <= 0:
            raise ValueError("executor_workers must be positive")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(f"invalid log_level: {self.log_level}")
        if self.log_format not in {"plain", "json"}:
            raise ValueError(f"invalid log_format: {self.log_format}")
        for p in self.provider_choice:
            if p not in {"fake", "gemini", "openrouter", "zai"}:
                raise ValueError(f"unknown provider: {p}")
        if "gemini" in self.provider_choice and not self.gemini_api_key:
            raise ValueError("gemini chosen but GEMINI_API_KEY not set")


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def load_config_from_env(
    overrides: dict[str, Any] | None = None,
) -> RuntimeConfig:
    """Load config in precedence order: overrides → env vars → defaults."""
    env = os.environ
    cfg_kwargs: dict[str, Any] = {}

    if "TURING_TICK_RATE_HZ" in env:
        cfg_kwargs["tick_rate_hz"] = _parse_int(env["TURING_TICK_RATE_HZ"], 100)
    if "TURING_EXECUTOR_WORKERS" in env:
        cfg_kwargs["executor_workers"] = _parse_int(
            env["TURING_EXECUTOR_WORKERS"], 8
        )
    if "TURING_DB_PATH" in env:
        cfg_kwargs["db_path"] = env["TURING_DB_PATH"]
    if "TURING_LOG_LEVEL" in env:
        cfg_kwargs["log_level"] = env["TURING_LOG_LEVEL"].upper()
    if "TURING_LOG_FORMAT" in env:
        cfg_kwargs["log_format"] = env["TURING_LOG_FORMAT"]
    if "TURING_METRICS_PORT" in env:
        cfg_kwargs["metrics_port"] = _parse_int(env["TURING_METRICS_PORT"], 0) or None
    if "TURING_PROVIDERS" in env:
        cfg_kwargs["provider_choice"] = tuple(
            p.strip() for p in env["TURING_PROVIDERS"].split(",") if p.strip()
        )
    if "GEMINI_API_KEY" in env:
        cfg_kwargs["gemini_api_key"] = env["GEMINI_API_KEY"]
    if "OPENROUTER_API_KEY" in env:
        cfg_kwargs["openrouter_api_key"] = env["OPENROUTER_API_KEY"]
    if "ZAI_API_KEY" in env:
        cfg_kwargs["zai_api_key"] = env["ZAI_API_KEY"]
    if "TURING_SCENARIO" in env:
        cfg_kwargs["scenario"] = env["TURING_SCENARIO"]
    if "TURING_SELF_LABEL" in env:
        cfg_kwargs["self_label"] = env["TURING_SELF_LABEL"]

    cfg = RuntimeConfig(**cfg_kwargs)
    if overrides:
        cfg = replace(cfg, **overrides)
    cfg.validate()
    return cfg
