"""CI gate for red team regression testing.

Compares current Warden detection rate against a stored baseline.
Fails if detection rate drops below baseline by more than the allowed regression margin.

Usage:
    python -m stronghold.redteam.ci_gate [--baseline PATH] [--current PATH] [--margin FLOAT]
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("stronghold.redteam.ci_gate")

DEFAULT_BASELINE_PATH = Path("tests/security/benchmark_baseline.json")
DEFAULT_REGRESSION_MARGIN = 0.02  # 2% allowed regression


@dataclass(frozen=True)
class GateResult:
    """Result of a CI red team gate check."""

    passed: bool
    baseline_rate: float
    current_rate: float
    regression: float  # positive = regression, negative = improvement
    details: str
    category_results: dict[str, dict[str, float]] = field(default_factory=dict)


def load_baseline(path: Path = DEFAULT_BASELINE_PATH) -> dict[str, Any]:
    """Load baseline from JSON file.

    Raises:
        FileNotFoundError: If the baseline file does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    text = path.read_text(encoding="utf-8")
    result: dict[str, Any] = json.loads(text)
    return result


def compare_results(
    baseline: dict[str, Any],
    current: dict[str, Any],
    margin: float = DEFAULT_REGRESSION_MARGIN,
) -> GateResult:
    """Compare current red team results against baseline.

    Checks both overall detection rate and per-category rates.
    Returns GateResult with passed=True if no category regressed beyond margin
    and overall rate did not regress beyond margin.
    """
    baseline_rate = float(baseline.get("overall_detection_rate", 0.0))
    current_rate = float(current.get("overall_detection_rate", 0.0))
    overall_regression = baseline_rate - current_rate

    baseline_cats: dict[str, Any] = baseline.get("categories", {})
    current_cats: dict[str, Any] = current.get("categories", {})

    # Union of all category keys from baseline (current-only categories don't regress)
    all_categories = set(baseline_cats.keys())

    category_results: dict[str, dict[str, float]] = {}
    category_failures: list[str] = []

    for cat in sorted(all_categories):
        b_rate = float(baseline_cats[cat].get("detection_rate", 0.0))
        c_data = current_cats.get(cat)
        c_rate = float(c_data.get("detection_rate", 0.0)) if c_data else 0.0
        diff = c_rate - b_rate  # positive = improvement, negative = regression

        category_results[cat] = {
            "baseline": b_rate,
            "current": c_rate,
            "diff": diff,
        }

        cat_regression = b_rate - c_rate
        if cat_regression > margin:
            category_failures.append(
                f"{cat}: {b_rate:.1%} -> {c_rate:.1%} (regression: {cat_regression:.1%})"
            )

    # Also include current-only categories (no regression possible)
    for cat in sorted(set(current_cats.keys()) - all_categories):
        c_rate = float(current_cats[cat].get("detection_rate", 0.0))
        category_results[cat] = {
            "baseline": 0.0,
            "current": c_rate,
            "diff": c_rate,
        }

    passed = overall_regression <= margin and len(category_failures) == 0

    if passed:
        if overall_regression < 0:
            details = (
                f"Detection rate improved: {baseline_rate:.1%} -> {current_rate:.1%} "
                f"(+{abs(overall_regression):.1%})"
            )
        else:
            details = (
                f"Detection rate stable: {baseline_rate:.1%} -> {current_rate:.1%} "
                f"(within {margin:.1%} margin)"
            )
    else:
        lines = [
            f"Regression detected: {baseline_rate:.1%} -> {current_rate:.1%} "
            f"(regression: {overall_regression:.1%}, margin: {margin:.1%})"
        ]
        if category_failures:
            lines.append("Category regressions:")
            lines.extend(f"  - {f}" for f in category_failures)
        details = "\n".join(lines)

    return GateResult(
        passed=passed,
        baseline_rate=baseline_rate,
        current_rate=current_rate,
        regression=overall_regression,
        details=details,
        category_results=category_results,
    )


def format_report(result: GateResult) -> str:
    """Format a human-readable report for CI output / PR comment."""
    status = "PASSED" if result.passed else "FAILED"
    lines = [
        f"Red Team Regression Gate: {status}",
        f"{'=' * 50}",
        f"Overall detection rate: {result.baseline_rate:.1%} (baseline)"
        f" -> {result.current_rate:.1%} (current)",
    ]

    if result.regression < 0:
        lines.append(f"Improvement: +{abs(result.regression):.1%}")
    elif result.regression > 0:
        lines.append(f"Regression: -{result.regression:.1%}")
    else:
        lines.append("No change in overall detection rate")

    if result.category_results:
        lines.append("")
        lines.append("Category breakdown:")
        for cat, data in sorted(result.category_results.items()):
            b = data["baseline"]
            c = data["current"]
            d = data["diff"]
            marker = "+" if d >= 0 else ""
            lines.append(f"  {cat}: {b:.1%} -> {c:.1%} ({marker}{d:.1%})")

    lines.append("")
    lines.append(result.details)

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for CI gate.

    Returns 0 if gate passes, 1 if it fails.
    """
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Red team CI regression gate")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help="Path to baseline JSON file",
    )
    parser.add_argument(
        "--current",
        type=Path,
        default=None,
        help="Path to current results JSON file (default: same as baseline for dry run)",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_REGRESSION_MARGIN,
        help=f"Allowed regression margin (default: {DEFAULT_REGRESSION_MARGIN})",
    )

    args = parser.parse_args(argv)

    try:
        baseline = load_baseline(args.baseline)
    except FileNotFoundError:
        logger.error("Baseline file not found: %s", args.baseline)
        print(f"ERROR: Baseline file not found: {args.baseline}")  # noqa: T201
        return 1

    # If no current results file specified, use baseline (dry run / self-check)
    if args.current is not None:
        try:
            current = load_baseline(args.current)
        except FileNotFoundError:
            logger.error("Current results file not found: %s", args.current)
            print(f"ERROR: Current results file not found: {args.current}")  # noqa: T201
            return 1
    else:
        current = baseline

    result = compare_results(baseline, current, margin=args.margin)
    report = format_report(result)
    print(report)  # noqa: T201

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
