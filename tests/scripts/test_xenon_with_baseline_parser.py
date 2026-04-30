"""Parser tests for scripts/xenon_with_baseline.py — covers Violation
extraction from xenon's ERROR-line output. Other behaviours (baseline
comparison, CLI, exit codes) live in sibling test modules.
"""

from __future__ import annotations

from xenon_with_baseline import Violation, parse_xenon_output


def test_parse_block_violation_extracts_file_block_and_rank() -> None:
    line = 'ERROR:xenon:block "src/stronghold/agents/base.py:185 handle" has a rank of F'
    assert parse_xenon_output(line) == [
        Violation(file="src/stronghold/agents/base.py", block="handle", rank="F")
    ]


def test_parse_module_violation_marks_block_as_literal_module() -> None:
    line = "ERROR:xenon:module 'src/stronghold/agents/base.py' has a rank of D"
    assert parse_xenon_output(line) == [
        Violation(file="src/stronghold/agents/base.py", block="module", rank="D")
    ]


def test_parse_handles_class_method_block_names_with_dot() -> None:
    line = 'ERROR:xenon:block "src/stronghold/conduit.py:140 Conduit.__init__" has a rank of D'
    [v] = parse_xenon_output(line)
    assert v.block == "Conduit.__init__"


def test_parse_returns_empty_for_clean_output() -> None:
    assert parse_xenon_output("") == []
    assert parse_xenon_output("INFO:xenon:scanning src/\n") == []


def test_parse_ignores_unrelated_log_lines_between_violations() -> None:
    text = (
        'ERROR:xenon:block "src/a.py:1 foo" has a rank of D\n'
        "INFO:xenon:processed 100 blocks\n"
        "ERROR:xenon:module 'src/b.py' has a rank of E\n"
    )
    violations = parse_xenon_output(text)
    assert [v.rank for v in violations] == ["D", "E"]
    assert [v.block for v in violations] == ["foo", "module"]


def test_parse_real_world_xenon_output_snapshot() -> None:
    """Snapshot of actual xenon output from src/stronghold/ at the time G-1
    was authored (16 violations, threshold C/C/C). If xenon's output format
    changes, this is the regression canary."""
    snapshot = (
        'ERROR:xenon:block "src/stronghold/conduit.py:193 route_request" has a rank of F\n'
        'ERROR:xenon:block "src/stronghold/conduit.py:140 Conduit" has a rank of D\n'
        'ERROR:xenon:block "src/stronghold/skills/fixer.py:13 fix_content" has a rank of E\n'
        "ERROR:xenon:module 'src/stronghold/agents/base.py' has a rank of D\n"
    )
    violations = parse_xenon_output(snapshot)
    assert len(violations) == 4
    assert violations[0] == Violation("src/stronghold/conduit.py", "route_request", "F")
    assert violations[-1] == Violation("src/stronghold/agents/base.py", "module", "D")


def test_violation_rank_comparison_is_worse_when_letter_increases() -> None:
    d = Violation(file="x", block="y", rank="D")
    assert d.is_worse_than("C")
    assert not d.is_worse_than("D")
    assert not d.is_worse_than("E")
