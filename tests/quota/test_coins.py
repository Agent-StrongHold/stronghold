"""Tests for coin-based quota ledger (pure functions + NoOpCoinLedger)."""

from __future__ import annotations

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


# ── _decimal ────────────────────────────────────────────────────────


def test_decimal_none_returns_default() -> None:
    from decimal import Decimal
    assert _decimal(None) == Decimal("0")
    assert _decimal(None, default="5") == Decimal("5")


def test_decimal_empty_string_returns_default() -> None:
    from decimal import Decimal
    assert _decimal("") == Decimal("0")


def test_decimal_numeric_string() -> None:
    from decimal import Decimal
    assert _decimal("1.5") == Decimal("1.5")


def test_decimal_int() -> None:
    from decimal import Decimal
    assert _decimal(42) == Decimal("42")


def test_decimal_invalid_returns_default() -> None:
    from decimal import Decimal
    assert _decimal("not a number") == Decimal("0")
    assert _decimal(object()) == Decimal("0")


# ── coins_to_microchips ─────────────────────────────────────────────


def test_coins_to_microchips_default_copper() -> None:
    # 1 copper = 1000 microchips
    assert coins_to_microchips(1) == 1000
    assert coins_to_microchips(5) == 5000


def test_coins_to_microchips_silver() -> None:
    # 1 silver = 10 copper = 10_000 microchips
    assert coins_to_microchips(1, "silver") == 10_000


def test_coins_to_microchips_gold() -> None:
    assert coins_to_microchips(1, "gold") == 100_000


def test_coins_to_microchips_platinum() -> None:
    assert coins_to_microchips(1, "platinum") == 500_000


def test_coins_to_microchips_diamond() -> None:
    assert coins_to_microchips(1, "diamond") == 1_000_000


def test_coins_to_microchips_unknown_denom_defaults_copper() -> None:
    assert coins_to_microchips(1, "magical") == 1000


def test_coins_to_microchips_none_denom_defaults_copper() -> None:
    # Exercise the "or copper" fallback
    assert coins_to_microchips(1, None) == 1000  # type: ignore[arg-type]


def test_coins_to_microchips_fractional() -> None:
    # 0.5 copper = 500 microchips
    assert coins_to_microchips("0.5") == 500


def test_coins_to_microchips_rounding() -> None:
    # 0.4995 copper ≈ 500 with ROUND_HALF_UP
    assert coins_to_microchips("0.4995") == 500


# ── format_microchips ───────────────────────────────────────────────


def test_format_microchips_zero() -> None:
    result = format_microchips(0)
    assert result["amount"] == 0
    assert result["denomination"] == "copper"


def test_format_microchips_copper() -> None:
    result = format_microchips(500)
    assert result["denomination"] == "copper"
    assert result["amount"] == 0.5


def test_format_microchips_silver() -> None:
    result = format_microchips(10_000)
    assert result["denomination"] == "silver"
    assert result["amount"] == 1.0


def test_format_microchips_gold() -> None:
    result = format_microchips(100_000)
    assert result["denomination"] == "gold"
    assert result["amount"] == 1.0


def test_format_microchips_diamond() -> None:
    result = format_microchips(1_000_000)
    assert result["denomination"] == "diamond"


def test_format_microchips_negative() -> None:
    result = format_microchips(-500)
    assert result["amount"] == -0.5
    assert result["microchips"] == -500


def test_format_microchips_preserves_raw() -> None:
    result = format_microchips(12345)
    assert result["microchips"] == 12345


# ── _find_model ─────────────────────────────────────────────────────


def test_find_model_by_key() -> None:
    models = {"gpt-4": {"provider": "openai"}}
    raw, key = _find_model(models, "gpt-4")
    assert key == "gpt-4"
    assert raw["provider"] == "openai"


def test_find_model_by_litellm_id() -> None:
    models = {"my-model": {"litellm_id": "openai/gpt-4o-mini"}}
    raw, key = _find_model(models, "openai/gpt-4o-mini")
    assert key == "my-model"
    assert raw["litellm_id"] == "openai/gpt-4o-mini"


def test_find_model_unknown_returns_empty() -> None:
    raw, key = _find_model({}, "missing-model")
    assert raw == {}
    assert key == "missing-model"


def test_find_model_non_dict_entry_skipped() -> None:
    """Non-dict entries in models dict should be handled gracefully."""
    models = {"bad-entry": "string-not-dict", "good": {"provider": "x"}}
    raw, key = _find_model(models, "bad-entry")
    assert raw == {}
    assert key == "bad-entry"


# ── _extract_provider ───────────────────────────────────────────────


def test_extract_provider_from_model() -> None:
    assert _extract_provider({"provider": "openai"}, {}, "gpt-4") == "openai"


def test_extract_provider_from_slash_prefix() -> None:
    assert _extract_provider({}, {"openai": {}}, "openai/gpt-4") == "openai"


def test_extract_provider_missing_returns_empty() -> None:
    assert _extract_provider({}, {}, "gpt-4") == ""


# ── _rate_value ─────────────────────────────────────────────────────


def test_rate_value_microchips_field_takes_precedence() -> None:
    model = {"coin_cost_base_microchips": 500, "coin_cost_base": 1}
    assert _rate_value(model, "coin_cost_base", default="0") == 500


def test_rate_value_from_denominated_amount() -> None:
    """If microchips field missing, compute from {field} + {field}_denomination."""
    model = {"coin_cost_base": 2, "coin_cost_base_denomination": "silver"}
    # 2 silver = 20000 microchips
    assert _rate_value(model, "coin_cost_base", default="0") == 20_000


def test_rate_value_default_when_missing() -> None:
    assert _rate_value({}, "coin_cost_base", default="0") == 0
    assert _rate_value({}, "coin_cost_base", default="1") == 1000  # 1 copper


# ── _resolve_denomination ───────────────────────────────────────────


def test_resolve_denomination_explicit() -> None:
    model = {"coin_denomination": "gold"}
    assert _resolve_denomination(model, 0, 0, 0) == "gold"


def test_resolve_denomination_explicit_invalid_falls_back() -> None:
    model = {"coin_denomination": "unicorn"}
    # Invalid → derives from cost
    assert _resolve_denomination(model, 0, 0, 0) == "copper"


def test_resolve_denomination_derives_from_cost() -> None:
    """Typical cost >= silver threshold → silver."""
    # 1 silver = 10 copper = 10000 microchips
    result = _resolve_denomination({}, 5000, 3000, 2000)
    assert result == "silver"  # total 10000 >= 1 silver


def test_resolve_denomination_cheap_is_copper() -> None:
    assert _resolve_denomination({}, 100, 50, 50) == "copper"


def test_resolve_denomination_expensive_is_diamond() -> None:
    # 1 diamond = 1000 copper = 1_000_000 microchips
    result = _resolve_denomination({}, 500_000, 300_000, 300_000)
    assert result == "diamond"


# ── _resolve_quote ──────────────────────────────────────────────────


def test_resolve_quote_empty_models_returns_default() -> None:
    quote = _resolve_quote({}, {}, "unknown", "openai", 100, 200)
    assert isinstance(quote, CoinQuote)
    assert quote.pricing_version == DEFAULT_PRICING_VERSION
    assert quote.model_key == "unknown"


def test_resolve_quote_computes_charge() -> None:
    models = {
        "m1": {
            "coin_cost_base_microchips": 100,
            "coin_cost_per_1k_input_microchips": 50,
            "coin_cost_per_1k_output_microchips": 100,
        },
    }
    quote = _resolve_quote(models, {}, "m1", "openai", 1000, 500)
    # base=100 + (1000/1000)*50 + (500/1000)*100 = 100 + 50 + 50 = 200
    assert quote.charged_microchips == 200
    assert quote.base_microchips == 100


def test_resolve_quote_negative_tokens_clamped() -> None:
    quote = _resolve_quote({}, {}, "m", "p", -100, -200)
    assert quote.charged_microchips >= 0


def test_resolve_quote_pricing_version_from_model() -> None:
    models = {"m": {"coin_pricing_version": "v2"}}
    quote = _resolve_quote(models, {}, "m", "p", 0, 0)
    assert quote.pricing_version == "v2"


def test_resolve_quote_pricing_version_from_provider() -> None:
    providers = {"openai": {"coin_pricing_version": "openai-v1"}}
    quote = _resolve_quote({}, providers, "m", "openai", 0, 0)
    assert quote.pricing_version == "openai-v1"


# ── NoOpCoinLedger ──────────────────────────────────────────────────


async def test_noop_ensure_can_afford_always_allows() -> None:
    ledger = NoOpCoinLedger()
    result = await ledger.ensure_can_afford(
        org_id="o", team_id="t", user_id="u",
        model_used="gpt-4", provider="openai",
        input_tokens=100, output_tokens=200,
    )
    assert result["allowed"] is True
    assert result["wallets"] == []
    assert "quote" in result


async def test_noop_charge_usage_returns_quote_data() -> None:
    ledger = NoOpCoinLedger()
    result = await ledger.charge_usage(
        request_id="r1", org_id="o", team_id="t", user_id="u",
        model_used="m", provider="p",
        input_tokens=100, output_tokens=200,
    )
    assert "charged_microchips" in result
    assert result["pricing_version"] == DEFAULT_PRICING_VERSION
    assert result["wallet_count"] == 0


async def test_noop_list_wallets_empty() -> None:
    ledger = NoOpCoinLedger()
    assert await ledger.list_wallets() == []


async def test_noop_get_banking_rate() -> None:
    ledger = NoOpCoinLedger()
    assert await ledger.get_banking_rate() == DEFAULT_BANKING_RATE_PCT


async def test_noop_set_banking_rate_raises() -> None:
    ledger = NoOpCoinLedger()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        await ledger.set_banking_rate(50)


async def test_noop_upsert_wallet_raises() -> None:
    ledger = NoOpCoinLedger()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        await ledger.upsert_wallet()


async def test_noop_get_subject_summary() -> None:
    ledger = NoOpCoinLedger()
    result = await ledger.get_subject_summary(org_id="o", team_id="t", user_id="u")
    assert result["wallets"] == []
    assert "denominations" in result


def test_noop_quote_returns_coin_quote() -> None:
    ledger = NoOpCoinLedger()
    quote = ledger.quote("m", "p", 100, 200)
    assert isinstance(quote, CoinQuote)


def test_noop_denominations_structure() -> None:
    denoms = NoOpCoinLedger.denominations()
    assert denoms["microchips_per_copper"] == MICROCHIPS_PER_COPPER
    assert denoms["factors"] == DENOMINATION_FACTORS


# ── Constants ───────────────────────────────────────────────────────


def test_all_denominations_defined() -> None:
    expected = {"copper", "silver", "gold", "platinum", "diamond"}
    assert set(DENOMINATION_FACTORS.keys()) == expected


def test_denomination_factors_ordered() -> None:
    """Factors must be monotonically increasing by denomination."""
    values = list(DENOMINATION_FACTORS.values())
    assert values == sorted(values)
