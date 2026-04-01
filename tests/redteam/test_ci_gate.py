"""Tests for red team CI gate — security regression detection.

Validates that the CI gate correctly compares current Warden detection
rates against a stored baseline and fails when regressions exceed the
allowed margin.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from stronghold.redteam.ci_gate import (
    DEFAULT_REGRESSION_MARGIN,
    GateResult,
    compare_results,
    format_report,
    load_baseline,
)


def _make_baseline(
    overall: float = 0.85,
    categories: dict[str, dict[str, float | int]] | None = None,
) -> dict[str, object]:
    """Build a baseline dict for testing."""
    if categories is None:
        categories = {
            "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
            "role_hijacking": {"detection_rate": 0.80, "total": 10, "detected": 8},
        }
    return {
        "overall_detection_rate": overall,
        "categories": categories,
        "timestamp": "2026-03-31T00:00:00Z",
    }


class TestLoadBaseline:
    """Tests for load_baseline."""

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        baseline_data = _make_baseline()
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(baseline_data))

        result = load_baseline(path)
        assert result["overall_detection_rate"] == 0.85
        assert "categories" in result

    def test_loads_categories(self, tmp_path: Path) -> None:
        baseline_data = _make_baseline()
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(baseline_data))

        result = load_baseline(path)
        cats = result["categories"]
        assert isinstance(cats, dict)
        assert "prompt_injection" in cats
        assert cats["prompt_injection"]["detection_rate"] == 0.90

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            load_baseline(tmp_path / "does_not_exist.json")

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{")
        with pytest.raises(json.JSONDecodeError):
            load_baseline(path)


class TestCompareResults:
    """Tests for compare_results."""

    def test_passes_when_current_equals_baseline(self) -> None:
        baseline = _make_baseline(overall=0.85)
        current = _make_baseline(overall=0.85)

        result = compare_results(baseline, current)
        assert result.passed is True
        assert result.regression == pytest.approx(0.0, abs=1e-9)

    def test_passes_when_current_exceeds_baseline(self) -> None:
        baseline = _make_baseline(overall=0.85)
        current = _make_baseline(overall=0.95)

        result = compare_results(baseline, current)
        assert result.passed is True
        assert result.regression < 0  # negative = improvement

    def test_passes_within_margin(self) -> None:
        baseline = _make_baseline(overall=0.85)
        # 1% regression, within default 2% margin
        current = _make_baseline(overall=0.84)

        result = compare_results(baseline, current)
        assert result.passed is True

    def test_fails_when_regression_exceeds_margin(self) -> None:
        baseline = _make_baseline(overall=0.85)
        # 5% regression, exceeds default 2% margin
        current = _make_baseline(overall=0.80)

        result = compare_results(baseline, current)
        assert result.passed is False
        assert result.regression > DEFAULT_REGRESSION_MARGIN

    def test_fails_on_per_category_regression(self) -> None:
        baseline = _make_baseline(
            overall=0.85,
            categories={
                "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
                "role_hijacking": {"detection_rate": 0.80, "total": 10, "detected": 8},
            },
        )
        current = _make_baseline(
            overall=0.85,
            categories={
                "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
                # 15% regression in role_hijacking, exceeds margin
                "role_hijacking": {"detection_rate": 0.65, "total": 10, "detected": 6},
            },
        )

        result = compare_results(baseline, current)
        assert result.passed is False
        assert "role_hijacking" in result.category_results

    def test_custom_margin(self) -> None:
        baseline = _make_baseline(overall=0.85)
        # 4% regression
        current = _make_baseline(overall=0.81)

        # With 5% margin, this should pass
        result = compare_results(baseline, current, margin=0.05)
        assert result.passed is True

        # With 3% margin, this should still pass (regression is exactly 0.04)
        result = compare_results(baseline, current, margin=0.03)
        assert result.passed is False

    def test_handles_missing_category_in_current(self) -> None:
        baseline = _make_baseline(
            overall=0.85,
            categories={
                "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
                "role_hijacking": {"detection_rate": 0.80, "total": 10, "detected": 8},
            },
        )
        # Current is missing role_hijacking
        current = _make_baseline(
            overall=0.85,
            categories={
                "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
            },
        )

        result = compare_results(baseline, current)
        # Missing category = treated as 0.0 detection rate => fails
        assert result.passed is False
        cat = result.category_results["role_hijacking"]
        assert cat["current"] == pytest.approx(0.0)

    def test_handles_new_category_in_current(self) -> None:
        baseline = _make_baseline(
            overall=0.85,
            categories={
                "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
            },
        )
        current = _make_baseline(
            overall=0.90,
            categories={
                "prompt_injection": {"detection_rate": 0.90, "total": 20, "detected": 18},
                "new_category": {"detection_rate": 0.70, "total": 10, "detected": 7},
            },
        )

        # New category has no baseline, so no regression possible — should pass
        result = compare_results(baseline, current)
        assert result.passed is True

    def test_gate_result_fields(self) -> None:
        baseline = _make_baseline(overall=0.85)
        current = _make_baseline(overall=0.82)

        result = compare_results(baseline, current)
        assert result.baseline_rate == pytest.approx(0.85)
        assert result.current_rate == pytest.approx(0.82)
        assert result.regression == pytest.approx(0.03, abs=1e-9)
        assert isinstance(result.details, str)
        assert isinstance(result.category_results, dict)

    def test_handles_empty_categories(self) -> None:
        baseline = _make_baseline(overall=0.85, categories={})
        current = _make_baseline(overall=0.85, categories={})

        result = compare_results(baseline, current)
        assert result.passed is True
        assert result.category_results == {}


class TestFormatReport:
    """Tests for format_report."""

    def test_passing_report_contains_pass(self) -> None:
        result = GateResult(
            passed=True,
            baseline_rate=0.85,
            current_rate=0.90,
            regression=-0.05,
            details="All clear",
            category_results={},
        )
        report = format_report(result)
        assert "PASS" in report.upper()

    def test_failing_report_contains_fail(self) -> None:
        result = GateResult(
            passed=False,
            baseline_rate=0.85,
            current_rate=0.80,
            regression=0.05,
            details="Regression detected",
            category_results={
                "prompt_injection": {
                    "baseline": 0.90,
                    "current": 0.80,
                    "diff": -0.10,
                },
            },
        )
        report = format_report(result)
        assert "FAIL" in report.upper()

    def test_report_contains_rates(self) -> None:
        result = GateResult(
            passed=True,
            baseline_rate=0.85,
            current_rate=0.90,
            regression=-0.05,
            details="Improved",
            category_results={
                "prompt_injection": {
                    "baseline": 0.90,
                    "current": 0.95,
                    "diff": 0.05,
                },
            },
        )
        report = format_report(result)
        assert "85" in report  # baseline rate
        assert "90" in report  # current rate

    def test_report_contains_category_details(self) -> None:
        result = GateResult(
            passed=False,
            baseline_rate=0.85,
            current_rate=0.80,
            regression=0.05,
            details="Regression in prompt_injection",
            category_results={
                "prompt_injection": {
                    "baseline": 0.90,
                    "current": 0.80,
                    "diff": -0.10,
                },
            },
        )
        report = format_report(result)
        assert "prompt_injection" in report

    def test_report_is_multiline(self) -> None:
        result = GateResult(
            passed=True,
            baseline_rate=0.85,
            current_rate=0.85,
            regression=0.0,
            details="No change",
            category_results={},
        )
        report = format_report(result)
        assert "\n" in report
