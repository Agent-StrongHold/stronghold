"""Tests for runtime/quota.py: FreeTierQuotaTracker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from turing.motivation import PRESSURE_MAX
from turing.runtime.providers.fake import FakeProvider
from turing.runtime.quota import FreeTierQuotaTracker


def test_register_and_pressure_nonzero() -> None:
    tracker = FreeTierQuotaTracker()
    provider = FakeProvider(
        name="p1",
        quota_allowed=1_000_000,
        quota_used=0,
        window_duration=timedelta(seconds=60),
    )
    tracker.register(provider, quality_weight=1.0)
    assert tracker.pressure_for("p1") > 0.0


def test_pressure_zero_when_headroom_zero() -> None:
    tracker = FreeTierQuotaTracker()
    provider = FakeProvider(
        name="p1",
        quota_allowed=1000,
        quota_used=1000,
        window_duration=timedelta(seconds=60),
    )
    tracker.register(provider)
    assert tracker.pressure_for("p1") == 0.0


def test_pressure_zero_for_unknown_pool() -> None:
    tracker = FreeTierQuotaTracker()
    assert tracker.pressure_for("does-not-exist") == 0.0


def test_pressure_clamped_to_max() -> None:
    tracker = FreeTierQuotaTracker()
    # Very large headroom, very short window → uncapped pressure would explode.
    provider = FakeProvider(
        name="p1",
        quota_allowed=10_000_000,
        quota_used=0,
        window_duration=timedelta(seconds=60),
    )
    tracker.register(provider, quality_weight=10.0)
    value = tracker.pressure_for("p1")
    assert value <= PRESSURE_MAX


def test_pressure_vec_has_entry_per_provider() -> None:
    tracker = FreeTierQuotaTracker()
    tracker.register(FakeProvider(name="a"))
    tracker.register(FakeProvider(name="b"))
    vec = tracker.pressure_vec()
    assert set(vec) == {"a", "b"}


def test_select_best_provider_prefers_higher_score() -> None:
    tracker = FreeTierQuotaTracker()
    low = FakeProvider(
        name="low",
        quota_allowed=1_000,
        quota_used=500,
        window_duration=timedelta(seconds=60),
    )
    high = FakeProvider(
        name="high",
        quota_allowed=1_000_000,
        quota_used=0,
        window_duration=timedelta(seconds=60),
    )
    tracker.register(low, quality_weight=0.5)
    tracker.register(high, quality_weight=1.0)
    assert tracker.select_best_provider() == "high"


def test_select_best_provider_none_when_all_depleted() -> None:
    tracker = FreeTierQuotaTracker()
    depleted = FakeProvider(
        name="d",
        quota_allowed=100,
        quota_used=100,
    )
    tracker.register(depleted)
    assert tracker.select_best_provider() is None


def test_pressure_rises_as_reset_approaches() -> None:
    """With fixed headroom, a shorter time-to-reset means higher pressure."""
    from datetime import datetime

    tracker = FreeTierQuotaTracker()
    # Modest headroom kept well under PRESSURE_MAX so clamping doesn't mask
    # the reset-proximity effect.
    provider = FakeProvider(
        name="p1",
        quota_allowed=1_000,
        quota_used=500,
        window_duration=timedelta(seconds=60),
    )
    tracker.register(provider, quality_weight=1.0)
    p_early = tracker.pressure_for("p1")

    provider._window_started = datetime.now(UTC) - timedelta(seconds=55)
    provider._quota_used = 500
    p_late = tracker.pressure_for("p1")

    assert p_late > p_early
