"""Tests for Thompson sampling variant selector."""

from __future__ import annotations

from stronghold.prompts.variant_selector import ThompsonSelector, VariantDistribution


class TestVariantDistribution:
    """VariantDistribution dataclass defaults and construction."""

    def test_default_alpha_beta(self) -> None:
        d = VariantDistribution(variant_id="v1")
        assert d.alpha == 1.0
        assert d.beta == 1.0

    def test_custom_alpha_beta(self) -> None:
        d = VariantDistribution(variant_id="v1", alpha=5.0, beta=3.0)
        assert d.alpha == 5.0
        assert d.beta == 3.0

    def test_variant_id_stored(self) -> None:
        d = VariantDistribution(variant_id="prompt-v2")
        assert d.variant_id == "prompt-v2"


class TestThompsonSelect:
    """ThompsonSelector.select picks a variant using Beta sampling."""

    def test_select_returns_one_of_variants(self) -> None:
        selector = ThompsonSelector()
        variants = ["a", "b", "c"]
        result = selector.select(variants)
        assert result in variants

    def test_select_single_variant_returns_it(self) -> None:
        selector = ThompsonSelector()
        result = selector.select(["only-one"])
        assert result == "only-one"

    def test_select_empty_raises(self) -> None:
        selector = ThompsonSelector()
        try:
            selector.select([])
            raise AssertionError("Expected ValueError")  # noqa: TRY301
        except ValueError:
            pass

    def test_select_biased_towards_better_variant(self) -> None:
        """A variant with many successes should be selected far more often."""
        selector = ThompsonSelector()
        # Give "winner" a strong prior: alpha=101, beta=1
        for _ in range(100):
            selector.record_outcome("winner", success=True)
        # Give "loser" a weak prior: alpha=1, beta=101
        for _ in range(100):
            selector.record_outcome("loser", success=False)

        counts: dict[str, int] = {"winner": 0, "loser": 0}
        for _ in range(500):
            pick = selector.select(["winner", "loser"])
            counts[pick] += 1

        # Winner should dominate (at least 90% of picks)
        assert counts["winner"] > 450


class TestRecordOutcome:
    """record_outcome updates alpha or beta correctly."""

    def test_success_increments_alpha(self) -> None:
        selector = ThompsonSelector()
        selector.record_outcome("v1", success=True)
        stats = selector.get_stats("v1")
        assert stats["alpha"] == 2.0  # 1.0 default + 1

    def test_failure_increments_beta(self) -> None:
        selector = ThompsonSelector()
        selector.record_outcome("v1", success=False)
        stats = selector.get_stats("v1")
        assert stats["beta"] == 2.0  # 1.0 default + 1

    def test_multiple_outcomes(self) -> None:
        selector = ThompsonSelector()
        for _ in range(5):
            selector.record_outcome("v1", success=True)
        for _ in range(3):
            selector.record_outcome("v1", success=False)
        stats = selector.get_stats("v1")
        assert stats["alpha"] == 6.0  # 1 + 5
        assert stats["beta"] == 4.0  # 1 + 3
        assert stats["trials"] == 8


class TestGetStats:
    """get_stats returns alpha, beta, mean, trials."""

    def test_stats_unknown_variant(self) -> None:
        selector = ThompsonSelector()
        stats = selector.get_stats("unknown")
        assert stats["alpha"] == 1.0
        assert stats["beta"] == 1.0
        assert stats["mean"] == 0.5
        assert stats["trials"] == 0

    def test_stats_mean_calculation(self) -> None:
        selector = ThompsonSelector()
        # 9 successes, 1 failure -> alpha=10, beta=2 -> mean = 10/12
        for _ in range(9):
            selector.record_outcome("v1", success=True)
        selector.record_outcome("v1", success=False)
        stats = selector.get_stats("v1")
        expected_mean = 10.0 / 12.0
        assert abs(stats["mean"] - expected_mean) < 1e-9


class TestAutoPromote:
    """should_auto_promote returns True when variant is clearly better."""

    def test_not_enough_trials(self) -> None:
        selector = ThompsonSelector()
        for _ in range(50):
            selector.record_outcome("v1", success=True)
        assert selector.should_auto_promote("v1", min_trials=100) is False

    def test_promote_when_strong_advantage(self) -> None:
        selector = ThompsonSelector()
        # 90 successes, 10 failures -> mean = 91/102 ~ 0.892
        for _ in range(90):
            selector.record_outcome("v1", success=True)
        for _ in range(10):
            selector.record_outcome("v1", success=False)
        # mean ~ 0.892 > 0.5 + 0.05 = 0.55
        assert selector.should_auto_promote("v1", min_trials=100, min_advantage=0.05) is True

    def test_no_promote_when_near_baseline(self) -> None:
        selector = ThompsonSelector()
        # 50 successes, 50 failures -> mean = 51/102 ~ 0.5
        for _ in range(50):
            selector.record_outcome("v1", success=True)
        for _ in range(50):
            selector.record_outcome("v1", success=False)
        assert selector.should_auto_promote("v1", min_trials=100, min_advantage=0.05) is False


class TestAutoDisable:
    """should_auto_disable returns True when variant is clearly worse."""

    def test_not_enough_trials(self) -> None:
        selector = ThompsonSelector()
        for _ in range(50):
            selector.record_outcome("v1", success=False)
        assert selector.should_auto_disable("v1", min_trials=100) is False

    def test_disable_when_strong_disadvantage(self) -> None:
        selector = ThompsonSelector()
        # 10 successes, 90 failures -> mean = 11/102 ~ 0.108
        for _ in range(10):
            selector.record_outcome("v1", success=True)
        for _ in range(90):
            selector.record_outcome("v1", success=False)
        # mean ~ 0.108 < 0.5 + (-0.05) = 0.45
        assert selector.should_auto_disable("v1", min_trials=100, max_disadvantage=-0.05) is True

    def test_no_disable_when_near_baseline(self) -> None:
        selector = ThompsonSelector()
        # 50 successes, 50 failures -> mean ~ 0.5
        for _ in range(50):
            selector.record_outcome("v1", success=True)
        for _ in range(50):
            selector.record_outcome("v1", success=False)
        assert selector.should_auto_disable("v1", min_trials=100, max_disadvantage=-0.05) is False
