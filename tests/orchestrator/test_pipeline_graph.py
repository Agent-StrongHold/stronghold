"""Tests for PipelineNode + PipelineGraph data model (story 15.1)."""

from __future__ import annotations

import pytest

from stronghold.orchestrator.graph import PipelineGraph, PipelineNode


def _node(name: str, depends_on: tuple[str, ...] = ()) -> PipelineNode:
    return PipelineNode(
        name=name,
        agent_name="test-agent",
        prompt_template="hello",
        depends_on=depends_on,
    )


# ── AC1: entry node (no deps) is ready with empty completed/skipped ──────────

def test_entry_node_ready_with_no_completed() -> None:
    graph = PipelineGraph([_node("plan")])
    ready = graph.ready(frozenset(), frozenset())
    assert any(n.name == "plan" for n in ready)


# ── AC2: node becomes ready after dep is completed ────────────────────────────

def test_node_ready_after_dep_completed() -> None:
    graph = PipelineGraph([_node("plan"), _node("code", depends_on=("plan",))])
    ready = graph.ready(frozenset({"plan"}), frozenset())
    names = {n.name for n in ready}
    assert "code" in names
    assert "plan" not in names


# ── AC3: skipped dep satisfies dependent ─────────────────────────────────────

def test_skipped_dep_satisfies_dependent() -> None:
    graph = PipelineGraph([_node("plan"), _node("code", depends_on=("plan",))])
    ready = graph.ready(frozenset(), frozenset({"plan"}))
    names = {n.name for n in ready}
    assert "code" in names


# ── AC4: node NOT ready when dep is pending ───────────────────────────────────

def test_node_not_ready_when_dep_pending() -> None:
    graph = PipelineGraph([_node("plan"), _node("code", depends_on=("plan",))])
    ready = graph.ready(frozenset(), frozenset())
    names = {n.name for n in ready}
    assert "code" not in names


# ── AC5: all deps required ────────────────────────────────────────────────────

def test_all_deps_required() -> None:
    nodes = [
        _node("A"),
        _node("B"),
        _node("merge", depends_on=("A", "B")),
    ]
    graph = PipelineGraph(nodes)
    # Only A is completed — merge must NOT be ready
    ready = graph.ready(frozenset({"A"}), frozenset())
    names = {n.name for n in ready}
    assert "merge" not in names


# ── AC6: completed node is not returned again ─────────────────────────────────

def test_completed_node_not_returned_again() -> None:
    graph = PipelineGraph([_node("plan"), _node("code", depends_on=("plan",))])
    ready = graph.ready(frozenset({"plan"}), frozenset())
    names = {n.name for n in ready}
    assert "plan" not in names


# ── AC7: valid linear graph passes validate ───────────────────────────────────

def test_valid_linear_graph_passes_validation() -> None:
    nodes = [
        _node("A"),
        _node("B", depends_on=("A",)),
        _node("C", depends_on=("B",)),
    ]
    graph = PipelineGraph(nodes)
    errors = graph.validate()
    assert errors == []


# ── AC8: cycle detected by validate ──────────────────────────────────────────

def test_cycle_detected_by_validate() -> None:
    nodes = [
        _node("A", depends_on=("B",)),
        _node("B", depends_on=("A",)),
    ]
    graph = PipelineGraph(nodes)
    errors = graph.validate()
    assert len(errors) > 0
    assert any("cycle" in e.lower() for e in errors)


# ── AC9: undeclared dep detected by validate ──────────────────────────────────

def test_undeclared_dep_detected_by_validate() -> None:
    graph = PipelineGraph([_node("B", depends_on=("ghost",))])
    errors = graph.validate()
    assert len(errors) > 0
    assert any("ghost" in e for e in errors)


# ── AC10: duplicate node name raises on construction ─────────────────────────

def test_duplicate_node_name_raises_on_construction() -> None:
    with pytest.raises(ValueError):
        PipelineGraph([_node("plan"), _node("plan")])


# ── extra: __len__ and __contains__ ──────────────────────────────────────────

def test_len_and_contains() -> None:
    graph = PipelineGraph([_node("A"), _node("B", depends_on=("A",))])
    assert len(graph) == 2
    assert "A" in graph
    assert "B" in graph
    assert "C" not in graph
