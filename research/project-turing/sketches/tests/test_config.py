"""Tests for turing/runtime/config.py — RuntimeConfig and load_config_from_env.

Spec:
    RuntimeConfig is a frozen dataclass with validation. load_config_from_env
    reads env vars (TURING_* and LITELLM_*) and applies overrides.

Acceptance criteria:
    1. Default RuntimeConfig has expected defaults.
    2. validate() raises on invalid tick_rate_hz, executor_workers, log_level, log_format.
    3. validate() raises when use_fake_provider=False without litellm fields.
    4. validate() passes when use_fake_provider=False with all litellm fields.
    5. load_config_from_env reads TURING_* env vars.
    6. load_config_from_env reads LITELLM_* env vars.
    7. load_config_from_env applies overrides over env vars.
    8. load_config_from_env falls back to defaults when no env vars set.
    9. _parse_bool handles true/1/yes/on and false/0/no/off.
    10. _parse_int handles valid and invalid integers.
    11. TURING_RSS_FEEDS is parsed as comma-separated tuple.
    12. TURING_METRICS_PORT=0 yields metrics_port=None.
"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest

from turing.runtime.config import RuntimeConfig, load_config_from_env, _parse_bool, _parse_int


class TestRuntimeConfigDefaults:
    def test_defaults(self) -> None:
        c = RuntimeConfig()
        assert c.tick_rate_hz == 100
        assert c.executor_workers == 8
        assert c.db_path == ":memory:"
        assert c.journal_dir is None
        assert c.log_level == "INFO"
        assert c.log_format == "plain"
        assert c.metrics_port is None
        assert c.use_fake_provider is True
        assert c.self_label == "default"

    def test_frozen(self) -> None:
        c = RuntimeConfig()
        with pytest.raises(AttributeError):
            c.tick_rate_hz = 200


class TestRuntimeConfigValidate:
    def test_valid_defaults(self) -> None:
        RuntimeConfig().validate()

    def test_tick_rate_hz_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz"):
            RuntimeConfig(tick_rate_hz=0).validate()

    def test_tick_rate_hz_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz"):
            RuntimeConfig(tick_rate_hz=-1).validate()

    def test_executor_workers_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="executor_workers"):
            RuntimeConfig(executor_workers=0).validate()

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValueError, match="log_level"):
            RuntimeConfig(log_level="VERBOSE").validate()

    def test_valid_log_levels(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            RuntimeConfig(log_level=level).validate()

    def test_invalid_log_format_raises(self) -> None:
        with pytest.raises(ValueError, match="log_format"):
            RuntimeConfig(log_format="xml").validate()

    def test_fake_provider_true_skips_litellm(self) -> None:
        RuntimeConfig(use_fake_provider=True).validate()

    def test_fake_provider_false_missing_base_url(self) -> None:
        with pytest.raises(ValueError, match="litellm_base_url"):
            RuntimeConfig(
                use_fake_provider=False,
                litellm_virtual_key="k",
                pools_config_path="/p",
            ).validate()

    def test_fake_provider_false_missing_virtual_key(self) -> None:
        with pytest.raises(ValueError, match="litellm_virtual_key"):
            RuntimeConfig(
                use_fake_provider=False,
                litellm_base_url="http://x",
                pools_config_path="/p",
            ).validate()

    def test_fake_provider_false_missing_pools_config(self) -> None:
        with pytest.raises(ValueError, match="pools_config_path"):
            RuntimeConfig(
                use_fake_provider=False,
                litellm_base_url="http://x",
                litellm_virtual_key="k",
            ).validate()

    def test_fake_provider_false_all_fields_valid(self) -> None:
        RuntimeConfig(
            use_fake_provider=False,
            litellm_base_url="http://litellm:4000",
            litellm_virtual_key="sk-key",
            pools_config_path="/etc/pools.yaml",
        ).validate()


class TestParseBool:
    @pytest.mark.parametrize("val", ["1", "true", "True", "TRUE", "yes", "Yes", "on", "ON"])
    def test_truthy(self, val: str) -> None:
        assert _parse_bool(val) is True

    @pytest.mark.parametrize("val", ["0", "false", "False", "no", "off", "OFF", "random"])
    def test_falsy(self, val: str) -> None:
        assert _parse_bool(val) is False


class TestParseInt:
    def test_valid_int(self) -> None:
        assert _parse_int("42", 0) == 42

    def test_invalid_int_returns_default(self) -> None:
        assert _parse_int("not_a_number", 99) == 99


class TestLoadConfigFromEnv:
    def test_no_env_returns_defaults(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TURING_", "LITELLM_"))}
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.tick_rate_hz == 100
            assert c.use_fake_provider is True
        finally:
            os.environ.clear()
            os.environ.update(env)

    def test_turing_tick_rate(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_TICK_RATE_HZ"] = "50"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.tick_rate_hz == 50
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_turing_log_level(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_LOG_LEVEL"] = "debug"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.log_level == "DEBUG"
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_turing_log_format_json(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_LOG_FORMAT"] = "json"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.log_format == "json"
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_turing_use_fake_provider_false(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TURING_", "LITELLM_"))}
        env["TURING_USE_FAKE_PROVIDER"] = "false"
        env["LITELLM_BASE_URL"] = "http://x"
        env["LITELLM_VIRTUAL_KEY"] = "k"
        env["TURING_POOLS_CONFIG"] = "/p"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.use_fake_provider is False
        finally:
            os.environ.clear()
            os.environ.update(
                {k: v for k, v in os.environ.items() if not k.startswith(("TURING_", "LITELLM_"))}
            )

    def test_litellm_env_vars(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("TURING_", "LITELLM_"))}
        env["LITELLM_BASE_URL"] = "http://litellm:4000"
        env["LITELLM_VIRTUAL_KEY"] = "sk-test"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.litellm_base_url == "http://litellm:4000"
            assert c.litellm_virtual_key == "sk-test"
        finally:
            os.environ.clear()
            os.environ.update(
                {k: v for k, v in os.environ.items() if not k.startswith(("TURING_", "LITELLM_"))}
            )

    def test_rss_feeds_parsed(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_RSS_FEEDS"] = "  https://a.com/feed , https://b.com/rss  ,  "
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.rss_feeds == ("https://a.com/feed", "https://b.com/rss")
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_metrics_port_zero_yields_none(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_METRICS_PORT"] = "0"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.metrics_port is None
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_metrics_port_valid(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_METRICS_PORT"] = "9090"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.metrics_port == 9090
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_overrides_take_precedence(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_TICK_RATE_HZ"] = "50"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env(overrides={"tick_rate_hz": 200})
            assert c.tick_rate_hz == 200
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_db_path_from_env(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_DB_PATH"] = "/tmp/test.db"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.db_path == "/tmp/test.db"
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_self_label_from_env(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_SELF_LABEL"] = "test-self"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.self_label == "test-self"
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_chat_port_from_env(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_CHAT_PORT"] = "8080"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.chat_port == 8080
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})

    def test_invalid_tick_rate_env_uses_default(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("TURING_")}
        env["TURING_TICK_RATE_HZ"] = "not_a_number"
        try:
            os.environ.clear()
            os.environ.update(env)
            c = load_config_from_env()
            assert c.tick_rate_hz == 100
        finally:
            os.environ.clear()
            os.environ.update({k: v for k, v in os.environ.items() if not k.startswith("TURING_")})
