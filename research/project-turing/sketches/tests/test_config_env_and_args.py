"""Additional coverage tests for config env loading.

Spec: Cover config.py env var loading branches.

Acceptance criteria:
- Config loads from all env vars correctly
- Invalid env values fall back to defaults
- Overrides take precedence over env vars
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from turing.runtime.config import RuntimeConfig, load_config_from_env


class TestConfigEnvLoading:
    def test_tick_rate_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_TICK_RATE_HZ": "200"}):
            cfg = load_config_from_env()
            assert cfg.tick_rate_hz == 200

    def test_executor_workers_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_EXECUTOR_WORKERS": "16"}):
            cfg = load_config_from_env()
            assert cfg.executor_workers == 16

    def test_db_path_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_DB_PATH": "/tmp/test.db"}):
            cfg = load_config_from_env()
            assert cfg.db_path == "/tmp/test.db"

    def test_journal_dir_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_JOURNAL_DIR": "/tmp/journal"}):
            cfg = load_config_from_env()
            assert cfg.journal_dir == "/tmp/journal"

    def test_log_level_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_LOG_LEVEL": "debug"}):
            cfg = load_config_from_env()
            assert cfg.log_level == "DEBUG"

    def test_log_format_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_LOG_FORMAT": "json"}):
            cfg = load_config_from_env()
            assert cfg.log_format == "json"

    def test_metrics_port_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_METRICS_PORT": "9090"}):
            cfg = load_config_from_env()
            assert cfg.metrics_port == 9090

    def test_metrics_bind_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_METRICS_BIND": "0.0.0.0"}):
            cfg = load_config_from_env()
            assert cfg.metrics_bind == "0.0.0.0"

    def test_use_fake_provider_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_USE_FAKE_PROVIDER": "true"}):
            cfg = load_config_from_env()
            assert cfg.use_fake_provider is True

    def test_litellm_base_url_from_env(self) -> None:
        with patch.dict(os.environ, {"LITELLM_BASE_URL": "http://localhost:4000"}):
            cfg = load_config_from_env()
            assert cfg.litellm_base_url == "http://localhost:4000"

    def test_litellm_virtual_key_from_env(self) -> None:
        with patch.dict(os.environ, {"LITELLM_VIRTUAL_KEY": "sk-test-123"}):
            cfg = load_config_from_env()
            assert cfg.litellm_virtual_key == "sk-test-123"

    def test_pools_config_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_POOLS_CONFIG": "/tmp/pools.yaml"}):
            cfg = load_config_from_env()
            assert cfg.pools_config_path == "/tmp/pools.yaml"

    def test_scenario_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_SCENARIO": "baseline"}):
            cfg = load_config_from_env()
            assert cfg.scenario == "baseline"

    def test_obsidian_vault_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_OBSIDIAN_VAULT": "/tmp/vault"}):
            cfg = load_config_from_env()
            assert cfg.obsidian_vault_dir == "/tmp/vault"

    def test_rss_feeds_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_RSS_FEEDS": "http://a.com/rss, http://b.com/rss"}):
            cfg = load_config_from_env()
            assert cfg.rss_feeds == ("http://a.com/rss", "http://b.com/rss")

    def test_chat_port_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_CHAT_PORT": "8443"}):
            cfg = load_config_from_env()
            assert cfg.chat_port == 8443

    def test_chat_bind_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_CHAT_BIND": "0.0.0.0"}):
            cfg = load_config_from_env()
            assert cfg.chat_bind == "0.0.0.0"

    def test_base_prompt_path_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_BASE_PROMPT_PATH": "/tmp/prompt.md"}):
            cfg = load_config_from_env()
            assert cfg.base_prompt_path == "/tmp/prompt.md"

    def test_self_label_from_env(self) -> None:
        with patch.dict(os.environ, {"TURING_SELF_LABEL": "production"}):
            cfg = load_config_from_env()
            assert cfg.self_label == "production"

    def test_metrics_port_zero_becomes_none(self) -> None:
        with patch.dict(os.environ, {"TURING_METRICS_PORT": "0"}):
            cfg = load_config_from_env()
            assert cfg.metrics_port is None

    def test_invalid_tick_rate_uses_default(self) -> None:
        with patch.dict(os.environ, {"TURING_TICK_RATE_HZ": "notanumber"}):
            cfg = load_config_from_env()
            assert cfg.tick_rate_hz == 100

    def test_overrides_take_precedence(self) -> None:
        cfg = load_config_from_env(overrides={"tick_rate_hz": 500})
        assert cfg.tick_rate_hz == 500
