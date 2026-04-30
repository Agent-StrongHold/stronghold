"""Baseline-comparison tests — covers load_baseline() and compare().

These exercise the §16.3.1 baseline-freeze semantics: a PR may carry
violations identical to the baseline, but a *new* offender or a *worse*
rank on a baselined offender is a fail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xenon_with_baseline import (
    BaselineError,
    Violation,
    compare,
    load_baseline,
)


def _baseline(*entries: tuple[str, str, str]) -> dict[str, object]:
    return {
        "generated_at": "2026-04-30T00:00:00Z",
        "command": "make baseline-xenon",
        "thresholds": {"absolute": "C", "modules": "C", "average": "C"},
        "permitted_above_threshold": [
            {"file": f, "block": b, "rank": r} for f, b, r in entries
        ],
    }


# ── load_baseline ──────────────────────────────────────────────────────────


def test_load_baseline_returns_parsed_dict(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_baseline(("src/x.py", "foo", "D"))))
    data = load_baseline(p)
    assert data["permitted_above_threshold"][0]["block"] == "foo"


def test_load_baseline_missing_raises_baseline_error(tmp_path: Path) -> None:
    with pytest.raises(BaselineError, match="not found"):
        load_baseline(tmp_path / "nope.json")


def test_load_baseline_malformed_json_raises_baseline_error(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text("{not json")
    with pytest.raises(BaselineError, match="not valid JSON"):
        load_baseline(p)


def test_load_baseline_top_level_array_rejected(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text("[]")
    with pytest.raises(BaselineError, match="JSON object"):
        load_baseline(p)


def test_load_baseline_permitted_must_be_list(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"permitted_above_threshold": "oops"}))
    with pytest.raises(BaselineError, match="must be a list"):
        load_baseline(p)


def test_load_baseline_entry_missing_required_key(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(
        json.dumps({"permitted_above_threshold": [{"file": "x", "rank": "D"}]})
    )
    with pytest.raises(BaselineError, match="file/block/rank"):
        load_baseline(p)


# ── compare ────────────────────────────────────────────────────────────────


def test_compare_returns_empty_when_no_violations() -> None:
    net_new, regressions = compare([], _baseline())
    assert net_new == [] and regressions == []


def test_compare_baseline_permitted_violation_is_neither_new_nor_regression() -> None:
    baseline = _baseline(("src/a.py", "foo", "D"))
    violation = Violation(file="src/a.py", block="foo", rank="D")
    net_new, regressions = compare([violation], baseline)
    assert net_new == []
    assert regressions == []


def test_compare_baseline_permits_strictly_better_rank() -> None:
    """A PR that improves a baselined block from D to C is permitted."""
    baseline = _baseline(("src/a.py", "foo", "D"))
    improved = Violation(file="src/a.py", block="foo", rank="C")
    net_new, regressions = compare([improved], baseline)
    assert net_new == []
    assert regressions == []


def test_compare_flags_net_new_when_file_not_in_baseline() -> None:
    baseline = _baseline(("src/known.py", "foo", "D"))
    new_offender = Violation(file="src/new.py", block="bar", rank="D")
    net_new, regressions = compare([new_offender], baseline)
    assert net_new == [new_offender]
    assert regressions == []


def test_compare_flags_net_new_when_block_in_known_file_is_new() -> None:
    """A new offender in an already-baselined file is still net-new."""
    baseline = _baseline(("src/a.py", "foo", "D"))
    new_block = Violation(file="src/a.py", block="bar", rank="D")
    net_new, regressions = compare([new_block], baseline)
    assert net_new == [new_block]
    assert regressions == []


def test_compare_flags_regression_when_baselined_block_gets_worse_rank() -> None:
    baseline = _baseline(("src/a.py", "foo", "D"))
    worsened = Violation(file="src/a.py", block="foo", rank="E")
    net_new, regressions = compare([worsened], baseline)
    assert net_new == []
    assert regressions == [worsened]


def test_compare_handles_module_level_baseline_entries() -> None:
    baseline = _baseline(("src/a.py", "module", "D"))
    same = Violation(file="src/a.py", block="module", rank="D")
    worse = Violation(file="src/a.py", block="module", rank="E")
    net_new, regressions = compare([same, worse], baseline)
    assert net_new == []
    assert regressions == [worse]


def test_compare_separates_new_and_regressions_in_one_pass() -> None:
    baseline = _baseline(("src/a.py", "foo", "D"))
    violations = [
        Violation(file="src/a.py", block="foo", rank="E"),  # regression
        Violation(file="src/b.py", block="bar", rank="D"),  # net-new file
        Violation(file="src/a.py", block="qux", rank="D"),  # net-new block
        Violation(file="src/a.py", block="foo", rank="D"),  # permitted
    ]
    net_new, regressions = compare(violations, baseline)
    assert {v.block for v in net_new} == {"bar", "qux"}
    assert [v.block for v in regressions] == ["foo"]
