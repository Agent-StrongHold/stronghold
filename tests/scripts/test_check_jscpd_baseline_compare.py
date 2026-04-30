"""load_baseline + compare tests for check_jscpd_baseline.py.

§16.4.3 enforces TWO things at once:
  (a) duplication_pct must stay ≤ baseline.max_duplication_pct (ceiling)
  (b) every clone pair must be in baseline.permitted_clone_pairs

Either failure → exit 1. Both clean → exit 0.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from check_jscpd_baseline import (
    BaselineError,
    ClonePair,
    compare,
    load_baseline,
)

if TYPE_CHECKING:
    from pathlib import Path


def _baseline(ceiling: float = 5.0, *pairs: tuple[str, str]) -> dict[str, object]:
    return {
        "generated_at": "2026-04-30T00:00:00Z",
        "command": "make baseline-jscpd",
        "max_duplication_pct": ceiling,
        "permitted_clone_pairs": [list(p) for p in pairs],
    }


def _clone(a: str, b: str, lines: int = 12, tokens: int = 100) -> ClonePair:
    pair = (a, b) if a <= b else (b, a)
    return ClonePair(file_pair=pair, lines=lines, tokens=tokens)


# ── load_baseline ──────────────────────────────────────────────────────────


def test_load_baseline_returns_parsed_dict(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_baseline(5.0, ("src/a.py", "src/b.py"))))
    data = load_baseline(p)
    assert data["max_duplication_pct"] == 5.0


def test_load_baseline_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(BaselineError, match="not found"):
        load_baseline(tmp_path / "nope.json")


def test_load_baseline_malformed_raises(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text("{not json")
    with pytest.raises(BaselineError, match="not valid JSON"):
        load_baseline(p)


def test_load_baseline_top_level_array_rejected(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text("[]")
    with pytest.raises(BaselineError, match="JSON object"):
        load_baseline(p)


def test_load_baseline_missing_ceiling_rejected(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"permitted_clone_pairs": []}))
    with pytest.raises(BaselineError, match="max_duplication_pct"):
        load_baseline(p)


def test_load_baseline_permitted_pairs_must_be_list(tmp_path: Path) -> None:
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"max_duplication_pct": 5.0, "permitted_clone_pairs": "oops"}))
    with pytest.raises(BaselineError, match="must be a list"):
        load_baseline(p)


# ── compare: percentage ceiling ────────────────────────────────────────────


def test_compare_pct_under_ceiling_returns_no_overrun() -> None:
    overrun, _new = compare(2.24, [], _baseline(5.0))
    assert overrun is None


def test_compare_pct_at_ceiling_is_acceptable() -> None:
    """The ceiling is inclusive — equality passes."""
    overrun, _new = compare(5.0, [], _baseline(5.0))
    assert overrun is None


def test_compare_pct_above_ceiling_returns_overrun_amount() -> None:
    overrun, _new = compare(5.5, [], _baseline(5.0))
    assert overrun == pytest.approx(0.5)


# ── compare: clone-pair set ────────────────────────────────────────────────


def test_compare_baseline_permitted_pair_is_not_net_new() -> None:
    baseline = _baseline(5.0, ("src/a.py", "src/b.py"))
    pair = _clone("src/a.py", "src/b.py")
    _, new = compare(1.0, [pair], baseline)
    assert new == []


def test_compare_baseline_permitted_pair_normalized_either_order() -> None:
    """Baseline lists ['src/z.py', 'src/a.py'] — a current clone of
    a↔z (or z↔a) must match."""
    baseline = _baseline(5.0, ("src/z.py", "src/a.py"))
    forward = _clone("src/a.py", "src/z.py")
    reverse = _clone("src/z.py", "src/a.py")
    _, n1 = compare(1.0, [forward], baseline)
    _, n2 = compare(1.0, [reverse], baseline)
    assert n1 == [] and n2 == []


def test_compare_unknown_pair_is_net_new() -> None:
    baseline = _baseline(5.0, ("src/a.py", "src/b.py"))
    new_pair = _clone("src/c.py", "src/d.py")
    _, new = compare(1.0, [new_pair], baseline)
    assert new == [new_pair]


def test_compare_size_drift_does_not_promote_to_net_new() -> None:
    """A baselined clone whose tokens grow shouldn't reappear as
    net-new — identity is the file pair, not the size."""
    baseline = _baseline(5.0, ("src/a.py", "src/b.py"))
    grown = _clone("src/a.py", "src/b.py", lines=30, tokens=400)
    _, new = compare(1.0, [grown], baseline)
    assert new == []


def test_compare_intra_file_pair_baselined() -> None:
    baseline = _baseline(5.0, ("src/a.py", "src/a.py"))
    intra = _clone("src/a.py", "src/a.py")
    _, new = compare(1.0, [intra], baseline)
    assert new == []


def test_compare_returns_both_overrun_and_net_new() -> None:
    baseline = _baseline(5.0, ("src/a.py", "src/b.py"))
    overrun, new = compare(
        7.0,
        [
            _clone("src/a.py", "src/b.py"),  # permitted
            _clone("src/x.py", "src/y.py"),  # net-new
        ],
        baseline,
    )
    assert overrun == pytest.approx(2.0)
    assert len(new) == 1
    assert new[0].file_pair == ("src/x.py", "src/y.py")


def test_compare_multiple_clones_same_file_pair_count_as_one_match() -> None:
    """If jscpd reports two clones between (a, b) — say at different
    line ranges — and the pair is baselined, BOTH are permitted.
    The pair-set semantics make this free."""
    baseline = _baseline(5.0, ("src/a.py", "src/b.py"))
    c1 = _clone("src/a.py", "src/b.py", lines=12)
    c2 = _clone("src/a.py", "src/b.py", lines=20)
    _, new = compare(1.0, [c1, c2], baseline)
    assert new == []
