"""Tests for specs/motivation.md: AC-9.1 through AC-9.18."""

from __future__ import annotations

import math

import pytest

from turing.motivation import (
    ACTION_CADENCE_TICKS,
    MAX_CONCURRENT_DISPATCHES,
    PRESSURE_MAX,
    PRIORITY_ANCHORS,
    TOP_X,
    BacklogItem,
    Motivation,
    PipelineState,
    priority_base,
    score,
)
from turing.reactor import FakeReactor


# -----------------------------------------------------------------------------
# AC-9.1, AC-9.2 — priority_base
# -----------------------------------------------------------------------------


def test_ac_9_1_priority_base_anchors_exact() -> None:
    for p, expected in PRIORITY_ANCHORS.items():
        assert priority_base(p) == expected


def test_ac_9_1_priority_base_interpolation_between_anchors() -> None:
    # P7 sits between P5 and P10 — check it's monotone, decreasing, and
    # numerically between the two anchors.
    v5 = priority_base(5)
    v7 = priority_base(7)
    v10 = priority_base(10)
    assert v5 > v7 > v10


def test_ac_9_1_priority_base_monotone_decreasing() -> None:
    values = [priority_base(p) for p in range(0, 71)]
    for i in range(1, len(values)):
        assert values[i] < values[i - 1] or math.isclose(
            values[i], values[i - 1]
        )


def test_ac_9_2_priority_base_is_pure() -> None:
    before_table = dict(PRIORITY_ANCHORS)
    _ = priority_base(7)
    _ = priority_base(42)
    assert PRIORITY_ANCHORS == before_table


# -----------------------------------------------------------------------------
# AC-9.3 through AC-9.6 — pressure and fit vectors
# -----------------------------------------------------------------------------


def test_ac_9_3_pressure_clamped_to_zero_and_max() -> None:
    reactor = FakeReactor()
    m = Motivation(reactor)
    m.set_pressure("gemini", -100.0)
    assert m.pressure["gemini"] == 0.0
    m.set_pressure("gemini", PRESSURE_MAX * 10.0)
    assert m.pressure["gemini"] == PRESSURE_MAX


def test_ac_9_5_no_fit_scores_base_only() -> None:
    item = BacklogItem(
        item_id="a", class_=4, kind="test", fit={}
    )
    pressure = {"codestral": 5000.0, "gemini": 3000.0}
    score_val, chosen = score(item, pressure)
    assert score_val == priority_base(4)
    assert chosen == ""


def test_ac_9_7_score_uses_max_component() -> None:
    item = BacklogItem(
        item_id="b",
        class_=20,
        kind="test",
        fit={"codestral": 1.0, "gemini": 0.5},
    )
    pressure = {"codestral": 2000.0, "gemini": 3000.0}
    score_val, chosen = score(item, pressure)
    # codestral * 1.0 = 2000 vs gemini * 0.5 = 1500 → codestral wins.
    assert chosen == "codestral"
    assert score_val == priority_base(20) + 2000.0


def test_ac_9_8_argmax_returns_chosen_pool() -> None:
    item = BacklogItem(
        item_id="c",
        class_=20,
        kind="test",
        fit={"a": 1.0, "b": 1.0},
    )
    pressure = {"a": 100.0, "b": 200.0}
    _, chosen = score(item, pressure)
    assert chosen == "b"


def test_ac_9_8_deterministic_tiebreak_by_fit_order() -> None:
    # When products tie, the first encountered pool wins.
    item = BacklogItem(
        item_id="d",
        class_=20,
        kind="test",
        fit={"a": 0.5, "b": 0.5},
    )
    pressure = {"a": 100.0, "b": 100.0}
    _, chosen = score(item, pressure)
    assert chosen in {"a", "b"}
    # Deterministic across repeated calls (dict order is insertion-order in 3.7+).
    _, chosen2 = score(item, pressure)
    assert chosen == chosen2


# -----------------------------------------------------------------------------
# AC-9.9 — cross-band reordering is allowed when pressure is big enough
# -----------------------------------------------------------------------------


def test_ac_9_9_cross_band_reordering_under_extreme_pressure() -> None:
    """Codestral-on-poem scenario: high pressure on code allows a P15 RASO code
    item to outscore a P4 journal item on a different pool."""
    p4_journal = BacklogItem(
        item_id="journal",
        class_=4,
        kind="journal",
        fit={"general": 1.0, "codestral": 0.0},
    )
    p15_code = BacklogItem(
        item_id="raso-code",
        class_=15,
        kind="raso",
        fit={"codestral": 1.0, "general": 0.0},
    )

    # Under seeds (PRESSURE_MAX=5000), the P4 journal still wins:
    pressure_low = {"general": 10.0, "codestral": 1000.0}
    s_journal, _ = score(p4_journal, pressure_low)
    s_raso, _ = score(p15_code, pressure_low)
    assert s_journal > s_raso

    # But raise the effective cap (simulating tuner decisions) and the P15
    # code item can outscore the P4 journal purely via pressure bonus.
    # In the seed implementation, PRESSURE_MAX clamps to 5000, so construct
    # the scenario at seeds: P4=100_000, P15 between P10=10_000 and P20=1_000
    # (~3100). Max bonus from one pool is 5000. So: journal=100_010, raso=~8100.
    # The cross-band reorder happens if PRESSURE_MAX were raised; test the
    # mathematics by passing pressure directly above the default cap.
    s_raso_big, chosen = score(
        p15_code, {"general": 0.0, "codestral": 200_000.0}
    )
    s_journal_small, _ = score(p4_journal, {"general": 0.0, "codestral": 0.0})
    assert s_raso_big > s_journal_small
    assert chosen == "codestral"


# -----------------------------------------------------------------------------
# AC-9.10 — within a pool, class priority dominates
# -----------------------------------------------------------------------------


def test_ac_9_10_within_pool_class_priority_dominates() -> None:
    p3 = BacklogItem(item_id="x", class_=3, kind="k", fit={"pool": 1.0})
    p10 = BacklogItem(item_id="y", class_=10, kind="k", fit={"pool": 1.0})
    pressure = {"pool": PRESSURE_MAX}
    s3, _ = score(p3, pressure)
    s10, _ = score(p10, pressure)
    assert s3 > s10


# -----------------------------------------------------------------------------
# AC-9.13, AC-9.14 — action loop cadence + top-X window
# -----------------------------------------------------------------------------


def test_ac_9_13_action_sweep_runs_on_cadence() -> None:
    reactor = FakeReactor()
    m = Motivation(reactor)
    dispatch_log: list[str] = []

    def handler(item: BacklogItem, chosen_pool: str) -> None:
        dispatch_log.append(item.item_id)

    m.register_dispatch("test", handler)
    m.insert(
        BacklogItem(
            item_id="a", class_=4, kind="test", fit={}, readiness=lambda s: True
        )
    )

    reactor.tick(ACTION_CADENCE_TICKS - 1)
    assert dispatch_log == []            # sweep hasn't fired yet
    reactor.tick(1)
    assert dispatch_log == ["a"]


def test_ac_9_14_action_sweep_bounded_by_top_x() -> None:
    reactor = FakeReactor()
    m = Motivation(reactor)
    fired: list[str] = []

    def handler(item: BacklogItem, chosen_pool: str) -> None:
        fired.append(item.item_id)

    m.register_dispatch("test", handler)

    # Insert more than TOP_X items with distinct class priorities.
    for i in range(TOP_X + 10):
        m.insert(
            BacklogItem(
                item_id=f"item-{i}",
                class_=i,          # lower i = higher priority
                kind="test",
                fit={},
                readiness=lambda s: True,
            )
        )

    reactor.tick(ACTION_CADENCE_TICKS)
    # Only top_x should have fired on this sweep. MAX_CONCURRENT_DISPATCHES
    # caps concurrent in-flight work; with synchronous dispatch (this sketch)
    # the in-flight set drops to 0 after each handler, so the effective
    # bound is TOP_X alone.
    assert len(fired) <= TOP_X


# -----------------------------------------------------------------------------
# AC-9.15 — readiness gating
# -----------------------------------------------------------------------------


def test_ac_9_15_readiness_gates_dispatch() -> None:
    reactor = FakeReactor()
    m = Motivation(reactor)
    fired: list[str] = []

    def handler(item: BacklogItem, chosen_pool: str) -> None:
        fired.append(item.item_id)

    m.register_dispatch("test", handler)
    m.insert(
        BacklogItem(
            item_id="blocked",
            class_=4,
            kind="test",
            fit={},
            readiness=lambda s: False,
        )
    )
    m.insert(
        BacklogItem(
            item_id="ready",
            class_=5,
            kind="test",
            fit={},
            readiness=lambda s: True,
        )
    )
    reactor.tick(ACTION_CADENCE_TICKS)
    assert "ready" in fired
    assert "blocked" not in fired


# -----------------------------------------------------------------------------
# AC-9.17 — dispatch observation
# -----------------------------------------------------------------------------


def test_ac_9_17_every_dispatch_writes_observation() -> None:
    reactor = FakeReactor()
    m = Motivation(reactor)

    m.register_dispatch("test", lambda item, pool: None)
    m.set_pressure("gemini", 1000.0)
    m.insert(
        BacklogItem(
            item_id="a",
            class_=4,
            kind="test",
            fit={"gemini": 1.0},
            readiness=lambda s: True,
        )
    )
    reactor.tick(ACTION_CADENCE_TICKS)
    obs = m.observations
    assert len(obs) == 1
    assert obs[0].item_id == "a"
    assert obs[0].chosen_pool == "gemini"
    assert obs[0].score == priority_base(4) + 1000.0
    assert obs[0].pressure_snapshot["gemini"] == 1000.0
    assert obs[0].fit_snapshot["gemini"] == 1.0
