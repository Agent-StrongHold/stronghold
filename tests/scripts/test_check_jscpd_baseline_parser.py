"""Parser tests for check_jscpd_baseline.parse_jscpd_report.

jscpd v4 emits a JSON report with `statistics.total.percentage` (lines-
duplication ratio) and a `duplicates` array of clone records. We extract
just the file-pair identity + size — line/token counts are informational
only; the baseline keys on the unordered file pair (§16.4.3).
"""

from __future__ import annotations

import json

from check_jscpd_baseline import ClonePair, parse_jscpd_report


def _report(pct: float, *clones: dict[str, object]) -> str:
    return json.dumps(
        {
            "statistics": {"total": {"percentage": pct}},
            "duplicates": list(clones),
        }
    )


def _clone(first: str, second: str, lines: int = 12, tokens: int = 100) -> dict[str, object]:
    return {
        "firstFile": {"name": first},
        "secondFile": {"name": second},
        "lines": lines,
        "tokens": tokens,
    }


def test_parser_extracts_global_percentage() -> None:
    pct, _ = parse_jscpd_report(_report(2.24))
    assert pct == 2.24


def test_parser_returns_zero_pct_when_field_missing() -> None:
    text = json.dumps({"statistics": {"total": {}}, "duplicates": []})
    pct, pairs = parse_jscpd_report(text)
    assert pct == 0.0
    assert pairs == []


def test_parser_extracts_single_clone_pair() -> None:
    text = _report(1.0, _clone("src/a.py", "src/b.py"))
    _, pairs = parse_jscpd_report(text)
    assert len(pairs) == 1
    assert pairs[0].file_pair == ("src/a.py", "src/b.py")


def test_parser_normalizes_pair_order() -> None:
    """A↔B and B↔A must produce identical baseline keys."""
    forward = _report(1.0, _clone("src/z.py", "src/a.py"))
    reverse = _report(1.0, _clone("src/a.py", "src/z.py"))
    _, p1 = parse_jscpd_report(forward)
    _, p2 = parse_jscpd_report(reverse)
    assert p1[0].file_pair == p2[0].file_pair == ("src/a.py", "src/z.py")


def test_parser_preserves_line_and_token_counts() -> None:
    text = _report(1.0, _clone("src/a.py", "src/b.py", lines=30, tokens=200))
    _, pairs = parse_jscpd_report(text)
    assert pairs[0].lines == 30
    assert pairs[0].tokens == 200


def test_parser_extracts_intra_file_clone() -> None:
    """jscpd reports clones within the same file too — both sides have
    the same name. We treat that as a (name, name) pair."""
    text = _report(1.0, _clone("src/a.py", "src/a.py"))
    _, pairs = parse_jscpd_report(text)
    assert pairs[0].file_pair == ("src/a.py", "src/a.py")


def test_parser_ignores_clones_with_missing_filename() -> None:
    """Defensive: malformed clone records (no firstFile or secondFile)
    are dropped rather than crashing — jscpd shouldn't emit these but
    if it does we don't want the gate to fall over."""
    text = _report(
        1.0,
        _clone("src/a.py", "src/b.py"),
        {"firstFile": {"name": "src/c.py"}, "secondFile": {}},
        {},
    )
    _, pairs = parse_jscpd_report(text)
    assert len(pairs) == 1


def test_parser_rejects_non_object_report() -> None:
    import pytest

    with pytest.raises(ValueError, match="JSON object"):
        parse_jscpd_report("[]")


def test_parser_handles_empty_duplicates() -> None:
    """Codebase below the dup threshold → percentage > 0 still possible
    (small repeated blocks under min-tokens), but `duplicates` empty."""
    text = _report(0.5)
    pct, pairs = parse_jscpd_report(text)
    assert pct == 0.5
    assert pairs == []


def test_clone_pair_key_is_just_the_file_pair() -> None:
    """Baseline-identity is the unordered file pair, NOT the size —
    a clone whose lines/tokens grow slightly should still match a
    baselined entry."""
    a = ClonePair(file_pair=("src/x.py", "src/y.py"), lines=10, tokens=50)
    b = ClonePair(file_pair=("src/x.py", "src/y.py"), lines=15, tokens=80)
    assert a.key == b.key
