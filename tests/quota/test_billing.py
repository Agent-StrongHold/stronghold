"""Tests for quota billing cycles and coin pricing / budget enforcement.

Covers:
  - billing.cycle_key: daily vs monthly key format
  - billing.daily_budget: normalization of free tokens
  - coins._decimal: safe coercion to Decimal
  - coins.coins_to_microchips: denomination scaling
  - coins.format_microchips: human-friendly rendering
  - coins._resolve_denomination: explicit vs derived denomination
  - coins._resolve_quote: full quote resolution with model/provider configs
  - coins._find_model: model lookup by key and litellm_id
  - coins._extract_provider: provider inference from model config
  - coins._rate_value: microchip vs denomination rate resolution
  - coins.NoOpCoinLedger: dev-mode ledger affordability + charging
  - coins.CoinQuote: dataclass construction
  - Constants: DENOMINATION_FACTORS, MICROCHIPS_PER_COPPER, DEFAULT_BANKING_RATE_PCT
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from stronghold.quota.billing import cycle_key, daily_budget
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

# ── billing.cycle_key ──────────────────────────────────────────────


class TestCycleKey:
    def test_daily_cycle_key_format(self) -> None:
        """Daily cycle key is YYYY-MM-DD format."""
        key = cycle_key("daily")
        parts = key.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day

    def test_monthly_cycle_key_format(self) -> None:
        """Monthly cycle key is YYYY-MM format."""
        key = cycle_key("monthly")
        parts = key.split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month

    def test_unknown_billing_cycle_defaults_to_monthly(self) -> None:
        """Any unrecognized billing_cycle falls through to monthly format."""
        key = cycle_key("quarterly")
        parts = key.split("-")
        assert len(parts) == 2


# ── billing.daily_budget ───────────────────────────────────────────


class TestDailyBudget:
    def test_daily_returns_exact(self) -> None:
        """Daily billing returns the full token budget as-is."""
        assert daily_budget(1000, "daily") == 1000.0

    def test_monthly_divides_by_30(self) -> None:
        """Monthly billing divides by 30 for daily normalization."""
        assert daily_budget(30000, "monthly") == 1000.0

    def test_monthly_float_result(self) -> None:
        """Monthly budget returns a float even when not evenly divisible."""
        result = daily_budget(1000, "monthly")
        assert isinstance(result, float)
        assert abs(result - 33.333) < 0.1

    def test_daily_returns_float_type(self) -> None:
        """Daily budget returns float type even for integer input."""
        result = daily_budget(500, "daily")
        assert isinstance(result, float)
        assert result == 500.0

    def test_zero_budget(self) -> None:
        """Zero free tokens yields zero daily budget in both cycles."""
        assert daily_budget(0, "daily") == 0.0
        assert daily_budget(0, "monthly") == 0.0


# ── coins._decimal ─────────────────────────────────────────────────


class TestDecimalCoercion:
    def test_none_returns_default(self) -> None:
        assert _decimal(None) == Decimal("0")

    def test_empty_string_returns_default(self) -> None:
        assert _decimal("") == Decimal("0")

    def test_custom_default(self) -> None:
        assert _decimal(None, default="5") == Decimal("5")

    def test_valid_integer(self) -> None:
        assert _decimal(42) == Decimal("42")

    def test_valid_float_string(self) -> None:
        assert _decimal("3.14") == Decimal("3.14")

    def test_garbage_returns_default(self) -> None:
        assert _decimal("not-a-number") == Decimal("0")

    def test_garbage_with_custom_default(self) -> None:
        assert _decimal(object(), default="99") == Decimal("99")


# ── coins.coins_to_microchips ─────────────────────────────────────


class TestCoinsToMicrochips:
    def test_one_copper_equals_1000_microchips(self) -> None:
        result = coins_to_microchips(1, "copper")
        assert result == 1_000

    def test_one_silver_equals_10_000_microchips(self) -> None:
        result = coins_to_microchips(1, "silver")
        assert result == 10_000

    def test_one_gold_equals_100_000_microchips(self) -> None:
        result = coins_to_microchips(1, "gold")
        assert result == 100_000

    def test_one_platinum_equals_500_000_microchips(self) -> None:
        result = coins_to_microchips(1, "platinum")
        assert result == 500_000

    def test_one_diamond_equals_1_000_000_microchips(self) -> None:
        result = coins_to_microchips(1, "diamond")
        assert result == 1_000_000

    def test_fractional_coins(self) -> None:
        """0.5 copper = 500 microchips."""
        result = coins_to_microchips("0.5", "copper")
        assert result == 500

    def test_default_denomination_is_copper(self) -> None:
        assert coins_to_microchips(2) == 2_000

    def test_unknown_denomination_treated_as_copper(self) -> None:
        assert coins_to_microchips(1, "unobtanium") == 1_000

    def test_none_amount_is_zero(self) -> None:
        assert coins_to_microchips(None) == 0

    def test_whitespace_denomination_stripped(self) -> None:
        assert coins_to_microchips(1, "  Silver  ") == 10_000

    def test_rounding_half_up(self) -> None:
        """Verify half-up rounding for fractional microchips."""
        # 0.0005 copper = 0.5 microchips -> rounds to 1
        result = coins_to_microchips("0.0005", "copper")
        assert result == 1


# ── coins.format_microchips ───────────────────────────────────────


class TestFormatMicrochips:
    def test_small_value_shows_copper(self) -> None:
        result = format_microchips(500)
        assert result["denomination"] == "copper"
        assert result["amount"] == 0.5
        assert result["microchips"] == 500

    def test_exact_one_copper(self) -> None:
        result = format_microchips(1_000)
        assert result["denomination"] == "copper"
        assert result["amount"] == 1.0

    def test_diamond_level(self) -> None:
        """1,000,000 microchips = 1 diamond."""
        result = format_microchips(1_000_000)
        assert result["denomination"] == "diamond"
        assert result["amount"] == 1.0

    def test_negative_microchips(self) -> None:
        result = format_microchips(-5_000)
        assert result["microchips"] == -5_000
        assert float(str(result["amount"])) < 0

    def test_zero_microchips(self) -> None:
        result = format_microchips(0)
        assert result["amount"] == 0.0
        assert result["microchips"] == 0

    def test_silver_threshold(self) -> None:
        """10,000 microchips = 1 silver (10 copper)."""
        result = format_microchips(10_000)
        assert result["denomination"] == "silver"
        assert result["amount"] == 1.0


# ── coins._resolve_denomination ────────────────────────────────────


class TestResolveDenomination:
    def test_explicit_denomination_takes_precedence(self) -> None:
        model_raw = {"coin_denomination": "gold"}
        result = _resolve_denomination(model_raw, 0, 0, 0)
        assert result == "gold"

    def test_explicit_denomination_case_insensitive(self) -> None:
        model_raw = {"coin_denomination": " Platinum "}
        result = _resolve_denomination(model_raw, 0, 0, 0)
        assert result == "platinum"

    def test_derived_from_typical_cost_copper(self) -> None:
        """Typical cost of 500 < 1000 (1 copper threshold) stays copper."""
        result = _resolve_denomination({}, 200, 150, 150)
        assert result == "copper"

    def test_derived_from_typical_cost_silver(self) -> None:
        """Typical cost of 10,000 qualifies for silver (factor=10)."""
        result = _resolve_denomination({}, 5_000, 3_000, 2_000)
        assert result == "silver"

    def test_derived_from_typical_cost_diamond(self) -> None:
        """Typical cost >= 1,000,000 qualifies for diamond."""
        result = _resolve_denomination({}, 500_000, 300_000, 200_000)
        assert result == "diamond"

    def test_invalid_explicit_denomination_falls_through(self) -> None:
        """Invalid explicit denomination falls through to derivation."""
        model_raw = {"coin_denomination": "mithril"}
        result = _resolve_denomination(model_raw, 0, 0, 0)
        # "mithril" not in DENOMINATION_FACTORS, falls through to derivation
        assert result == "copper"


# ── coins._find_model ─────────────────────────────────────────────


class TestFindModel:
    def test_exact_key_match(self) -> None:
        models = {"gpt-4": {"provider": "openai", "quality": 0.9}}
        raw, key = _find_model(models, "gpt-4")
        assert key == "gpt-4"
        assert raw["provider"] == "openai"

    def test_litellm_id_match(self) -> None:
        models = {"gpt-4": {"litellm_id": "openai/gpt-4", "quality": 0.9}}
        raw, key = _find_model(models, "openai/gpt-4")
        assert key == "gpt-4"

    def test_no_match_returns_empty_dict(self) -> None:
        raw, key = _find_model({}, "nonexistent")
        assert raw == {}
        assert key == "nonexistent"

    def test_non_dict_model_entry(self) -> None:
        """If a model entry is not a dict, return empty dict."""
        models = {"broken": "not-a-dict"}
        raw, key = _find_model(models, "broken")
        assert raw == {}
        assert key == "broken"


# ── coins._extract_provider ───────────────────────────────────────


class TestExtractProvider:
    def test_explicit_provider_in_model_config(self) -> None:
        model_raw = {"provider": "anthropic"}
        result = _extract_provider(model_raw, {}, "claude-3")
        assert result == "anthropic"

    def test_infer_from_slash_prefix(self) -> None:
        """If model_used has 'openai/gpt-4', check providers dict."""
        providers = {"openai": {"status": "active"}}
        result = _extract_provider({}, providers, "openai/gpt-4")
        assert result == "openai"

    def test_slash_prefix_not_in_providers(self) -> None:
        result = _extract_provider({}, {}, "openai/gpt-4")
        assert result == ""

    def test_no_provider_no_slash(self) -> None:
        result = _extract_provider({}, {}, "gpt-4")
        assert result == ""


# ── coins._rate_value ──────────────────────────────────────────────


class TestRateValue:
    def test_microchips_field_takes_precedence(self) -> None:
        """If <field>_microchips exists, use it directly."""
        model_raw = {
            "coin_cost_base": "5",
            "coin_cost_base_microchips": 7777,
        }
        result = _rate_value(model_raw, "coin_cost_base", default="0")
        assert result == 7777

    def test_falls_back_to_denomination_conversion(self) -> None:
        """Without _microchips suffix, convert via denomination."""
        model_raw = {"coin_cost_base": "2", "coin_cost_base_denomination": "silver"}
        result = _rate_value(model_raw, "coin_cost_base", default="0")
        # 2 silver = 2 * 10 * 1000 = 20,000
        assert result == 20_000

    def test_default_denomination_is_copper(self) -> None:
        model_raw = {"coin_cost_base": "3"}
        result = _rate_value(model_raw, "coin_cost_base", default="0")
        assert result == 3_000

    def test_missing_field_uses_default(self) -> None:
        result = _rate_value({}, "coin_cost_per_1k_input", default="1")
        assert result == 1_000


# ── coins._resolve_quote ──────────────────────────────────────────


class TestResolveQuote:
    def test_empty_config_uses_defaults(self) -> None:
        """With no model/provider config, uses default rates."""
        quote = _resolve_quote({}, {}, "unknown-model", "", 1000, 500)
        assert isinstance(quote, CoinQuote)
        assert quote.model_key == "unknown-model"
        assert quote.pricing_version == DEFAULT_PRICING_VERSION
        # Default: base=0, input=1 copper/1k, output=2 copper/1k
        # input cost = 1000/1000 * 1000 = 1000 microchips
        # output cost = 500/1000 * 2000 = 1000 microchips
        assert quote.charged_microchips == 2000

    def test_custom_model_rates(self) -> None:
        models = {
            "gpt-4": {
                "provider": "openai",
                "coin_cost_base": "0",
                "coin_cost_per_1k_input": "5",
                "coin_cost_per_1k_output": "15",
            },
        }
        quote = _resolve_quote(models, {}, "gpt-4", "", 2000, 1000)
        # input: 2000/1000 * 5_000 = 10_000
        # output: 1000/1000 * 15_000 = 15_000
        assert quote.charged_microchips == 25_000
        assert quote.provider == "openai"

    def test_provider_pricing_version(self) -> None:
        models = {"m": {"provider": "p"}}
        providers = {"p": {"coin_pricing_version": "provider-v2"}}
        quote = _resolve_quote(models, providers, "m", "", 0, 0)
        assert quote.pricing_version == "provider-v2"

    def test_model_pricing_version_overrides_provider(self) -> None:
        models = {"m": {"provider": "p", "coin_pricing_version": "model-v3"}}
        providers = {"p": {"coin_pricing_version": "provider-v2"}}
        quote = _resolve_quote(models, providers, "m", "", 0, 0)
        assert quote.pricing_version == "model-v3"

    def test_negative_tokens_treated_as_zero(self) -> None:
        quote = _resolve_quote({}, {}, "m", "", -100, -200)
        # Negative tokens are floored to 0
        assert quote.charged_microchips == 0

    def test_zero_tokens_yields_base_only(self) -> None:
        models = {"m": {"coin_cost_base": "10"}}
        quote = _resolve_quote(models, {}, "m", "", 0, 0)
        assert quote.charged_microchips == 10_000

    def test_explicit_provider_arg_used(self) -> None:
        """Explicit provider arg takes precedence over model config."""
        models = {"m": {"provider": "from-config"}}
        quote = _resolve_quote(models, {}, "m", "from-arg", 0, 0)
        assert quote.provider == "from-arg"


# ── coins.NoOpCoinLedger ──────────────────────────────────────────


class TestNoOpCoinLedger:
    async def test_ensure_can_afford_always_allows(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.ensure_can_afford(
            org_id="org-1",
            team_id="team-1",
            user_id="user-1",
            model_used="gpt-4",
            provider="openai",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result["allowed"] is True
        assert result["wallets"] == []

    async def test_charge_usage_returns_zero_wallet_count(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.charge_usage(
            request_id="req-1",
            org_id="org-1",
            team_id="team-1",
            user_id="user-1",
            model_used="gpt-4",
            provider="openai",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result["wallet_count"] == 0
        assert int(str(result["charged_microchips"])) > 0

    async def test_list_wallets_empty(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.list_wallets(org_id="org-1")
        assert result == []

    async def test_get_banking_rate(self) -> None:
        ledger = NoOpCoinLedger()
        rate = await ledger.get_banking_rate()
        assert rate == DEFAULT_BANKING_RATE_PCT

    async def test_set_banking_rate_raises(self) -> None:
        ledger = NoOpCoinLedger()
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await ledger.set_banking_rate(50)

    async def test_upsert_wallet_raises(self) -> None:
        ledger = NoOpCoinLedger()
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            await ledger.upsert_wallet()

    async def test_get_subject_summary(self) -> None:
        ledger = NoOpCoinLedger()
        result = await ledger.get_subject_summary(
            org_id="org-1", team_id="team-1", user_id="user-1"
        )
        assert "wallets" in result
        assert result["wallets"] == []
        denoms = result["denominations"]
        assert isinstance(denoms, dict)
        assert denoms["microchips_per_copper"] == MICROCHIPS_PER_COPPER

    def test_quote_uses_defaults(self) -> None:
        ledger = NoOpCoinLedger()
        quote = ledger.quote("gpt-4", "openai", 1000, 500)
        assert isinstance(quote, CoinQuote)
        assert quote.charged_microchips > 0

    def test_denominations_static(self) -> None:
        result = NoOpCoinLedger.denominations()
        assert result["microchips_per_copper"] == MICROCHIPS_PER_COPPER
        assert result["factors"] is DENOMINATION_FACTORS


# ── coins.CoinQuote ───────────────────────────────────────────────


class TestCoinQuote:
    def test_frozen_dataclass(self) -> None:
        quote = CoinQuote(
            base_microchips=100,
            input_rate_microchips=1_000,
            output_rate_microchips=2_000,
            charged_microchips=5_000,
            pricing_version="v1",
            model_key="gpt-4",
            provider="openai",
            denomination="copper",
        )
        assert quote.charged_microchips == 5_000
        with pytest.raises(AttributeError):
            quote.charged_microchips = 999  # type: ignore[misc]


# ── Constants ──────────────────────────────────────────────────────


class TestConstants:
    def test_microchips_per_copper(self) -> None:
        assert MICROCHIPS_PER_COPPER == 1_000

    def test_default_banking_rate(self) -> None:
        assert DEFAULT_BANKING_RATE_PCT == 40

    def test_denomination_factor_ordering(self) -> None:
        """Denomination factors must increase monotonically."""
        factors = list(DENOMINATION_FACTORS.values())
        assert factors == sorted(factors)

    def test_all_denominations_present(self) -> None:
        expected = {"copper", "silver", "gold", "platinum", "diamond"}
        assert set(DENOMINATION_FACTORS.keys()) == expected
