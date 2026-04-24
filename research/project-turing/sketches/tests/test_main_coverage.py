"""Coverage gap filler for turing/runtime/main.py helper functions and arg parsing.

Spec: _build_providers non-fake path, _pool_roles non-fake path, _parse_rss_reflection
with non-dict JSON (array), _make_imagine_for_provider with empty reply,
build_and_run arg override paths.

Acceptance criteria:
- _build_providers raises ValueError when pools config has no pools
- _pool_roles returns correct roles from pools config
- _parse_rss_reflection handles JSON array (non-dict)
- _make_imagine_for_provider handles empty string reply
- build_and_run parses --tick-rate, --db, --log-level, --use-fake-provider flags
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from turing.runtime.config import RuntimeConfig
from turing.runtime.main import (
    DEFAULT_BASE_PROMPT,
    _build_providers,
    _load_base_prompt,
    _make_imagine_for_provider,
    _parse_rss_reflection,
    _pool_roles,
)
from turing.runtime.providers.fake import FakeProvider
from turing.types import EpisodicMemory, MemoryTier, SourceKind


class TestBuildProvidersNonFake:
    def test_raises_when_no_pools(self, tmp_path: Path) -> None:
        pools_file = tmp_path / "pools.yaml"
        pools_file.write_text("pools: []\n")
        cfg = RuntimeConfig(
            use_fake_provider=False,
            litellm_base_url="http://localhost:4000",
            litellm_virtual_key="sk-test",
            pools_config_path=str(pools_file),
        )
        with pytest.raises(ValueError, match="no pools"):
            _build_providers(cfg)

    def test_builds_from_config(self, tmp_path: Path) -> None:
        pools_file = tmp_path / "pools.yaml"
        pools_file.write_text(
            textwrap.dedent("""\
            pools:
              - pool_name: gemini-flash
                model: gemini/gemini-2.0-flash
                window_kind: rpm
                window_duration_seconds: 60
                tokens_allowed: 1000000
                quality_weight: 0.7
                role: chat
        """)
        )
        cfg = RuntimeConfig(
            use_fake_provider=False,
            litellm_base_url="http://localhost:4000",
            litellm_virtual_key="sk-test",
            pools_config_path=str(pools_file),
        )
        providers, weights = _build_providers(cfg)
        assert "gemini-flash" in providers
        assert weights["gemini-flash"] == 0.7


class TestPoolRolesNonFake:
    def test_returns_roles_from_config(self, tmp_path: Path) -> None:
        pools_file = tmp_path / "pools.yaml"
        pools_file.write_text(
            textwrap.dedent("""\
            pools:
              - pool_name: chat-pool
                model: model-a
                window_kind: rpm
                window_duration_seconds: 60
                tokens_allowed: 1000000
                quality_weight: 0.8
                role: chat
              - pool_name: emb-pool
                model: model-b
                window_kind: rpm
                window_duration_seconds: 60
                tokens_allowed: 500000
                quality_weight: 0.5
                role: embedding
        """)
        )
        cfg = RuntimeConfig(
            use_fake_provider=False,
            litellm_base_url="http://localhost:4000",
            litellm_virtual_key="sk-test",
            pools_config_path=str(pools_file),
        )
        roles = _pool_roles(cfg)
        assert roles["chat-pool"] == "chat"
        assert roles["emb-pool"] == "embedding"


class TestParseRssReflectionEdgeCases:
    def test_json_array_returns_defaults(self) -> None:
        result = _parse_rss_reflection("[1, 2, 3]", fallback_summary="fb")
        assert result["summary"] == "fb"
        assert result["actionable"] is False

    def test_non_json_object(self) -> None:
        result = _parse_rss_reflection("42", fallback_summary="fb")
        assert result["summary"] == "fb"

    def test_json_with_null_fields(self) -> None:
        result = _parse_rss_reflection(
            '{"opinion": null, "proposed_action": null, "interest_score": null, "actionable": null, "summary": null}',
            fallback_summary="fb",
        )
        assert result["summary"] == "fb"


class TestMakeImagineEdgeCases:
    def test_empty_reply_uses_provider_name(self) -> None:
        provider = FakeProvider(name="test-provider", responses=[""])
        imagine = _make_imagine_for_provider(provider)
        seed = EpisodicMemory(
            memory_id="s1",
            self_id="self",
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="test seed",
            weight=0.3,
            intent_at_time="test",
        )
        result = imagine(seed, [], "pool1")
        assert len(result) == 1
        assert "test-provider" in result[0][1]


class TestRunArgsOverrides:
    def test_all_none_returns_empty(self) -> None:
        from turing.runtime.main import RunArgs

        args = RunArgs()
        assert args.to_overrides() == {}

    def test_tick_rate_maps_to_hz(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(tick_rate=10).to_overrides()
        assert overrides["tick_rate_hz"] == 10

    def test_db_maps_to_db_path(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(db="/tmp/test.db").to_overrides()
        assert overrides["db_path"] == "/tmp/test.db"

    def test_litellm_url_disables_fake(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(litellm_base_url="http://llm:4000").to_overrides()
        assert overrides["litellm_base_url"] == "http://llm:4000"
        assert overrides["use_fake_provider"] is False

    def test_litellm_key_maps(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(litellm_virtual_key="sk-abc").to_overrides()
        assert overrides["litellm_virtual_key"] == "sk-abc"

    def test_pools_config_maps(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(pools_config="/p/pools.yaml").to_overrides()
        assert overrides["pools_config_path"] == "/p/pools.yaml"

    def test_scenario_maps(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(scenario="baseline").to_overrides()
        assert overrides["scenario"] == "baseline"

    def test_rss_feeds_splits_commas(self) -> None:
        from turing.runtime.main import RunArgs

        overrides = RunArgs(rss_feeds="a, b ,c").to_overrides()
        assert overrides["rss_feeds"] == ("a", "b", "c")

    def test_full_coverage(self) -> None:
        from turing.runtime.main import RunArgs

        args = RunArgs(
            tick_rate=5,
            db="test.db",
            journal_dir="/j",
            log_level="DEBUG",
            log_format="json",
            use_fake_provider=True,
            litellm_base_url="http://x",
            litellm_virtual_key="sk-x",
            pools_config="/p.yaml",
            scenario="s",
            metrics_port=9090,
            metrics_bind="0.0.0.0",
            chat_port=8080,
            chat_bind="0.0.0.0",
            obsidian_vault="/vault",
            rss_feeds="feed1,feed2",
            base_prompt="/prompt.md",
        )
        o = args.to_overrides()
        assert o["tick_rate_hz"] == 5
        assert o["db_path"] == "test.db"
        assert o["journal_dir"] == "/j"
        assert o["log_level"] == "DEBUG"
        assert o["log_format"] == "json"
        assert o["use_fake_provider"] is False  # litellm_base_url overrides
        assert o["litellm_base_url"] == "http://x"
        assert o["litellm_virtual_key"] == "sk-x"
        assert o["pools_config_path"] == "/p.yaml"
        assert o["scenario"] == "s"
        assert o["metrics_port"] == 9090
        assert o["metrics_bind"] == "0.0.0.0"
        assert o["chat_port"] == 8080
        assert o["chat_bind"] == "0.0.0.0"
        assert o["obsidian_vault_dir"] == "/vault"
        assert o["rss_feeds"] == ("feed1", "feed2")
        assert o["base_prompt_path"] == "/prompt.md"
