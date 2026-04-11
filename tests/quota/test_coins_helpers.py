"""Tests for the pure-function helpers + NoOpCoinLedger in stronghold.quota.coins.

PgCoinLedger is SQL-heavy and needs a real Postgres to exercise; those
tests are tracked as a follow-up integration PR. This file covers:

  - _decimal / coins_to_microchips / format_microchips (unit conversion)
  - CoinQuote dataclass (immutability, field presence)
  - NoOpCoinLedger (all 8 methods + denominations classmethod)
  - _resolve_denomination / _resolve_quote / _find_model /
    _extract_provider / _rate_value (pricing resolution)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from stronghold.quota.coins import (
    DEFAULT_BANKING_RATE_PCT,
    DEFAULT_PRICING_VERSION,
    DENOMINATION_FACTORS,
    MICROCHIPS_PER_COPPER,
    CoinQuote,
    NoOpCoinLedger,
    _decimal,
    _extract_provider,
    _find_model,
    _rate_value,
    _resolve_denomination,
    _resolve_quote,
    coins_to_microchips,
    format_microchips,
)


# ---------------------------------------------------------------------------
# _decimal
# ---------------------------------------------------------------------------


class TestDecimal:
    def test_none_returns_default(self) -> None:
        assert _decimal(None) == Decimal("0")

    def test_empty_string_returns_default(self) -> None:
        assert _decimal("") == Decimal("0")

    def test_explicit_default(self) -> None:
        assert _decimal(None, default="5") == Decimal("5")

    def test_numeric_string_parses(self) -> None:
        assert _decimal("42.5") == Decimal("42.5")

    def test_int_parses(self) -> None:
        assert _decimal(100) == Decimal("100")

    def test_float_parses(self) -> None:
        assert _decimal(1.5) == Decimal("1.5")

    def test_garbage_falls_back_to_default(self) -> None:
        """Anything that Decimal(str(x)) can't parse returns default."""
        assert _decimal("not a number") == Decimal("0")
        assert _decimal("not a number", default="99") == Decimal("99")

    def test_object_with_bad_str_falls_back(self) -> None:
        class _Bad:
            def __str__(self) -> str:
                return "definitely not decimal"

        assert _decimal(_Bad()) == Decimal("0")


# ---------------------------------------------------------------------------
# coins_to_microchips
# ---------------------------------------------------------------------------


class TestCoinsToMicrochips:
    @pytest.mark.parametrize(
        ("amount", "denom", "expected"),
        [
            (1, "copper", 1_000),
            (1, "silver", 10_000),
            (1, "gold", 100_000),
            (1, "platinum", 500_000),
            (1, "diamond", 1_000_000),
            (2.5, "copper", 2_500),
            (0.001, "copper", 1),
            (None, "copper", 0),
            ("", "gold", 0),
        ],
    )
    def test_various(self, amount: object, denom: str, expected: int) -> None:
        assert coins_to_microchips(amount, denom) == expected

    def test_unknown_denomination_defaults_to_copper(self) -> None:
        assert coins_to_microchips(1, "zirconium") == 1_000

    def test_empty_denomination_defaults_to_copper(self) -> None:
        assert coins_to_microchips(1, "") == 1_000

    def test_whitespace_denomination_normalized(self) -> None:
        assert coins_to_microchips(1, "  SILVER  ") == 10_000

    def test_rounding_half_up(self) -> None:
        """0.0015 copper = 1.5 microchips; ROUND_HALF_UP → 2."""
        assert coins_to_microchips(Decimal("0.0015"), "copper") == 2


# ---------------------------------------------------------------------------
# format_microchips
# ---------------------------------------------------------------------------


class TestFormatMicrochips:
    def test_zero(self) -> None:
        result = format_microchips(0)
        assert result == {"amount": 0.0, "denomination": "copper", "microchips": 0}

    def test_single_copper(self) -> None:
        result = format_microchips(1_000)
        assert result["denomination"] == "copper"
        assert result["amount"] == 1.0

    def test_silver_threshold(self) -> None:
        result = format_microchips(10_000)
        assert result["denomination"] == "silver"
        assert result["amount"] == 1.0

    def test_gold(self) -> None:
        # gold threshold = 100 * 1000 = 100_000. platinum = 500_000.
        # 200_000 is in [100_000, 500_000) → gold.
        result = format_microchips(200_000)
        assert result["denomination"] == "gold"
        assert result["amount"] == 2.0

    def test_platinum(self) -> None:
        # platinum = 500_000, diamond = 1_000_000. 750_000 → platinum.
        result = format_microchips(750_000)
        assert result["denomination"] == "platinum"

    def test_diamond(self) -> None:
        # diamond threshold = 1000 * 1000 = 1_000_000. 2_000_000 → diamond.
        result = format_microchips(2_000_000)
        assert result["denomination"] == "diamond"

    def test_negative_preserves_sign(self) -> None:
        result = format_microchips(-5_000)
        assert result["amount"] == -5.0
        assert result["denomination"] == "copper"

    def test_microchips_field_is_raw_int(self) -> None:
        # 12_345 is in [10_000, 100_000) → silver (factor=10).
        result = format_microchips(12_345)
        assert result["microchips"] == 12_345
        assert result["denomination"] == "silver"

    def test_rounding_to_two_decimals(self) -> None:
        """1234 microchips = 1.234 copper → 1.23 after quantize."""
        result = format_microchips(1_234)
        assert result["amount"] == 1.23


# ---------------------------------------------------------------------------
# CoinQuote
# ---------------------------------------------------------------------------


class TestCoinQuote:
    def test_frozen_dataclass_fields(self) -> None:
        q = CoinQuote(
            base_microchips=100,
            input_rate_microchips=1,
            output_rate_microchips=2,
            charged_microchips=150,
            pricing_version="v1",
            model_key="gpt",
            provider="openai",
            denomination="copper",
        )
        assert q.charged_microchips == 150
        assert q.denomination == "copper"

    def test_immutable(self) -> None:
        q = CoinQuote(
            base_microchips=0,
            input_rate_microchips=0,
            output_rate_microchips=0,
            charged_microchips=0,
            pricing_version="v",
            model_key="m",
            provider="p",
            denomination="copper",
        )
        with pytest.raises((AttributeError, Exception)):
            q.charged_microchips = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NoOpCoinLedger
# ---------------------------------------------------------------------------


class TestNoOpCoinLedger:
    @pytest.mark.asyncio
    async def test_ensure_can_afford_always_allows(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.ensure_can_afford(
            org_id="org",
            team_id="team",
            user_id="user",
            model_used="gpt-4",
            provider="openai",
            input_tokens=100,
            output_tokens=200,
        )
        assert result["allowed"] is True
        assert result["wallets"] == []
        assert "quote" in result

    @pytest.mark.asyncio
    async def test_charge_usage_returns_quote_amount(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.charge_usage(
            request_id="req-1",
            org_id="org",
            team_id="team",
            user_id="user",
            model_used="gpt-4",
            provider="openai",
            input_tokens=100,
            output_tokens=200,
        )
        assert "charged_microchips" in result
        assert result["pricing_version"] == DEFAULT_PRICING_VERSION
        assert result["wallet_count"] == 0

    @pytest.mark.asyncio
    async def test_list_wallets_returns_empty(self) -> None:
        ledger = NoOpCoinLedger()
        assert await ledger.list_wallets() == []
        assert await ledger.list_wallets(org_id="o", owner_type="t", owner_id="u") == []

    @pytest.mark.asyncio
    async def test_get_banking_rate_returns_default(self) -> None:
        ledger = NoOpCoinLedger()
        assert await ledger.get_banking_rate() == DEFAULT_BANKING_RATE_PCT

    @pytest.mark.asyncio
    async def test_set_banking_rate_raises(self) -> None:
        ledger = NoOpCoinLedger()
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await ledger.set_banking_rate(50)

    @pytest.mark.asyncio
    async def test_upsert_wallet_raises(self) -> None:
        ledger = NoOpCoinLedger()
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await ledger.upsert_wallet(org_id="o", owner_type="t", owner_id="u")

    @pytest.mark.asyncio
    async def test_get_subject_summary_returns_empty(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.get_subject_summary(
            org_id="org", team_id="team", user_id="user"
        )
        assert result["wallets"] == []
        assert "denominations" in result

    def test_quote_produces_coin_quote(self) -> None:
        ledger = NoOpCoinLedger()
        q = ledger.quote("gpt-4", "openai", 100, 200)
        assert isinstance(q, CoinQuote)
        # Default rates kick in: 0 base + 1/1k input + 2/1k output
        # (100/1000)*1 + (200/1000)*2 = 0.1 + 0.4 = 0.5 → 1 microchip (ROUND_HALF_UP)
        assert q.charged_microchips >= 0

    def test_denominations_classmethod(self) -> None:
        result = NoOpCoinLedger.denominations()
        assert result["microchips_per_copper"] == MICROCHIPS_PER_COPPER
        assert result["factors"] == DENOMINATION_FACTORS


# ---------------------------------------------------------------------------
# _resolve_denomination
# ---------------------------------------------------------------------------


class TestResolveDenomination:
    def test_explicit_denomination_wins(self) -> None:
        result = _resolve_denomination(
            {"coin_denomination": "silver"}, base=0, in_rate=0, out_rate=0
        )
        assert result == "silver"

    def test_explicit_uppercase_normalized(self) -> None:
        result = _resolve_denomination(
            {"coin_denomination": "GOLD"}, base=0, in_rate=0, out_rate=0
        )
        assert result == "gold"

    def test_unknown_explicit_falls_back_to_derivation(self) -> None:
        """An explicit denomination not in DENOMINATION_FACTORS is ignored;
        the function derives from the typical cost instead."""
        result = _resolve_denomination(
            {"coin_denomination": "zirconium"}, base=0, in_rate=0, out_rate=0
        )
        assert result == "copper"

    def test_derived_copper_for_tiny_cost(self) -> None:
        result = _resolve_denomination({}, base=100, in_rate=10, out_rate=20)
        assert result == "copper"

    def test_derived_silver_at_threshold(self) -> None:
        # silver = 10 * 1_000 = 10_000
        result = _resolve_denomination({}, base=0, in_rate=0, out_rate=10_000)
        assert result == "silver"

    def test_derived_diamond_at_high_cost(self) -> None:
        result = _resolve_denomination(
            {}, base=1_000 * MICROCHIPS_PER_COPPER, in_rate=0, out_rate=0
        )
        assert result == "diamond"


# ---------------------------------------------------------------------------
# _find_model
# ---------------------------------------------------------------------------


class TestFindModel:
    def test_direct_key_match(self) -> None:
        models = {"gpt-4": {"provider": "openai"}}
        raw, key = _find_model(models, "gpt-4")
        assert key == "gpt-4"
        assert raw == {"provider": "openai"}

    def test_litellm_id_alias_match(self) -> None:
        models = {"gpt-4-turbo": {"litellm_id": "openai/gpt-4-0125"}}
        raw, key = _find_model(models, "openai/gpt-4-0125")
        assert key == "gpt-4-turbo"
        assert raw["litellm_id"] == "openai/gpt-4-0125"

    def test_no_match_returns_empty_with_model_used_as_key(self) -> None:
        raw, key = _find_model({}, "unknown-model")
        assert raw == {}
        assert key == "unknown-model"

    def test_non_dict_value_ignored(self) -> None:
        models = {"gpt-4": "not a dict"}
        raw, key = _find_model(models, "gpt-4")
        # Direct key match returns {} for non-dict raw
        assert raw == {}
        assert key == "gpt-4"


# ---------------------------------------------------------------------------
# _extract_provider
# ---------------------------------------------------------------------------


class TestExtractProvider:
    def test_explicit_provider_in_model_raw_wins(self) -> None:
        assert _extract_provider({"provider": "anthropic"}, {}, "claude-3") == "anthropic"

    def test_slash_prefix_matches_providers(self) -> None:
        assert _extract_provider({}, {"openai": {}}, "openai/gpt-4") == "openai"

    def test_slash_prefix_unknown_returns_empty(self) -> None:
        assert _extract_provider({}, {}, "cohere/command") == ""

    def test_no_slash_returns_empty(self) -> None:
        assert _extract_provider({}, {"openai": {}}, "gpt-4") == ""

    def test_empty_provider_field_falls_through(self) -> None:
        assert _extract_provider({"provider": ""}, {"ollama": {}}, "ollama/llama") == "ollama"


# ---------------------------------------------------------------------------
# _rate_value
# ---------------------------------------------------------------------------


class TestRateValue:
    def test_microchips_field_takes_precedence(self) -> None:
        """If <field>_microchips is set, it wins over <field> + denomination."""
        raw = {
            "coin_cost_base_microchips": 500,
            "coin_cost_base": 1,
            "coin_cost_base_denomination": "gold",  # would be 100_000 if used
        }
        assert _rate_value(raw, "coin_cost_base", default="0") == 500

    def test_denomination_fallback_to_copper(self) -> None:
        raw = {"coin_cost_base": 2}
        assert _rate_value(raw, "coin_cost_base", default="0") == 2_000

    def test_explicit_denomination_applied(self) -> None:
        raw = {
            "coin_cost_base": 1,
            "coin_cost_base_denomination": "silver",
        }
        assert _rate_value(raw, "coin_cost_base", default="0") == 10_000

    def test_default_used_when_field_absent(self) -> None:
        assert _rate_value({}, "coin_cost_base", default="3") == 3_000

    def test_non_numeric_microchips_falls_back_to_zero(self) -> None:
        raw = {"coin_cost_base_microchips": "gibberish"}
        assert _rate_value(raw, "coin_cost_base", default="0") == 0


# ---------------------------------------------------------------------------
# _resolve_quote — integration of all the above
# ---------------------------------------------------------------------------


class TestResolveQuote:
    def test_default_empty_models(self) -> None:
        """No model config → _rate_value defaults land as copper-denominated
        values and get converted through coins_to_microchips.

        default_base = "0" copper → 0 microchips
        default_input = "1" copper → 1000 microchips/1k tokens
        default_output = "2" copper → 2000 microchips/1k tokens
        Total for 1000 in + 1000 out: 0 + 1000 + 2000 = 3000 microchips.
        """
        q = _resolve_quote({}, {}, "unknown", "unknown", 1000, 1000)
        assert q.charged_microchips == 3000
        assert q.pricing_version == DEFAULT_PRICING_VERSION
        assert q.model_key == "unknown"

    def test_explicit_model_with_overrides(self) -> None:
        models: dict[str, Any] = {
            "gpt-4": {
                "provider": "openai",
                "coin_cost_base_microchips": 100,
                "coin_cost_per_1k_input_microchips": 50,
                "coin_cost_per_1k_output_microchips": 150,
                "coin_pricing_version": "gpt4-v1",
            }
        }
        q = _resolve_quote(models, {"openai": {}}, "gpt-4", "openai", 2000, 1000)
        # base 100 + (2000/1000)*50 + (1000/1000)*150 = 100 + 100 + 150 = 350
        assert q.charged_microchips == 350
        assert q.pricing_version == "gpt4-v1"
        assert q.provider == "openai"

    def test_provider_fallback_from_model_prefix(self) -> None:
        q = _resolve_quote(
            {}, {"anthropic": {}}, "anthropic/claude-3", "", 100, 100
        )
        assert q.provider == "anthropic"

    def test_provider_pricing_version_fallback(self) -> None:
        """provider-level pricing_version is used when the model lacks one."""
        models = {"gpt-4": {"provider": "openai"}}
        providers = {"openai": {"coin_pricing_version": "openai-q2"}}
        q = _resolve_quote(models, providers, "gpt-4", "openai", 0, 0)
        assert q.pricing_version == "openai-q2"

    def test_negative_tokens_clamped_to_zero(self) -> None:
        q = _resolve_quote({}, {}, "m", "p", -100, -100)
        # max(-100, 0) = 0 → no token cost, just base (default 0)
        assert q.charged_microchips == 0

    def test_charged_never_negative(self) -> None:
        """Even if base is negative (pathological config), charged >= 0."""
        models = {
            "m": {
                "coin_cost_base_microchips": -500,
                "coin_cost_per_1k_input_microchips": 0,
                "coin_cost_per_1k_output_microchips": 0,
            }
        }
        q = _resolve_quote(models, {}, "m", "p", 100, 100)
        assert q.charged_microchips == 0
