"""Tests for turing/runtime/providers/fake.py — FakeProvider.

Spec:
    FakeProvider returns canned responses with configurable latency and
    failure modes. Never makes network calls.

Acceptance criteria:
    1. Default construction yields a provider named "fake" returning "fake response".
    2. complete() cycles through provided responses.
    3. fail_every=N raises RateLimited every N-th call.
    4. unavailable_every=N raises ProviderUnavailable every N-th call.
    5. quota_window() returns FreeTierWindow with correct state.
    6. quota_window() resets when the window duration has elapsed.
    7. embed() returns deterministic 64-dim vectors; same input → same output.
    8. embed() returns different vectors for different inputs.
    9. embed() increments quota_used.
    10. latency_s > 0 causes sleep in complete().
    11. complete() increments quota_used proportional to prompt + max_tokens.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from turing.runtime.providers.base import FreeTierWindow, ProviderUnavailable, RateLimited
from turing.runtime.providers.fake import FakeProvider


class TestFakeProviderDefault:
    def test_default_name(self) -> None:
        p = FakeProvider()
        assert p.name == "fake"

    def test_default_response(self) -> None:
        p = FakeProvider()
        assert p.complete("hello") == "fake response"

    def test_custom_name(self) -> None:
        p = FakeProvider(name="custom")
        assert p.name == "custom"


class TestFakeProviderResponses:
    def test_cycles_through_responses(self) -> None:
        p = FakeProvider(responses=["a", "b", "c"])
        assert p.complete("x") == "a"
        assert p.complete("x") == "b"
        assert p.complete("x") == "c"
        assert p.complete("x") == "a"

    def test_single_response_cycles(self) -> None:
        p = FakeProvider(responses=["only"])
        for _ in range(10):
            assert p.complete("x") == "only"


class TestFakeProviderRateLimited:
    def test_fail_every_3(self) -> None:
        p = FakeProvider(fail_every=3)
        assert p.complete("a") == "fake response"
        assert p.complete("b") == "fake response"
        with pytest.raises(RateLimited, match="call 3"):
            p.complete("c")

    def test_fail_every_never(self) -> None:
        p = FakeProvider(fail_every=0)
        for _ in range(10):
            assert p.complete("x") == "fake response"


class TestFakeProviderUnavailable:
    def test_unavailable_every_2(self) -> None:
        p = FakeProvider(unavailable_every=2)
        assert p.complete("a") == "fake response"
        with pytest.raises(ProviderUnavailable, match="call 2"):
            p.complete("b")

    def test_unavailable_every_never(self) -> None:
        p = FakeProvider(unavailable_every=0)
        for _ in range(10):
            assert p.complete("x") == "fake response"


class TestFakeProviderLatency:
    def test_latency_simulated(self) -> None:
        p = FakeProvider(latency_s=0.1)
        start = time.monotonic()
        p.complete("x")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08

    def test_zero_latency_is_fast(self) -> None:
        p = FakeProvider(latency_s=0.0)
        start = time.monotonic()
        p.complete("x")
        elapsed = time.monotonic() - start
        assert elapsed < 0.05


class TestFakeProviderQuotaWindow:
    def test_quota_window_returns_window(self) -> None:
        p = FakeProvider(quota_allowed=5000, quota_used=100)
        w = p.quota_window()
        assert isinstance(w, FreeTierWindow)
        assert w.tokens_allowed == 5000
        assert w.tokens_used == 100
        assert w.provider == "fake"
        assert w.window_kind == "rpm"

    def test_quota_window_increments_on_complete(self) -> None:
        p = FakeProvider()
        p.complete("a" * 40, max_tokens=20)
        w = p.quota_window()
        assert w.tokens_used == 40 // 4 + 20 // 4

    def test_quota_window_resets_after_duration(self) -> None:
        p = FakeProvider(
            quota_allowed=10000, quota_used=5000, window_duration=timedelta(seconds=60)
        )
        p._window_started = datetime.now(UTC) - timedelta(seconds=61)
        w = p.quota_window()
        assert w.tokens_used == 0

    def test_custom_window_kind(self) -> None:
        p = FakeProvider(window_kind="daily", window_duration=timedelta(hours=24))
        w = p.quota_window()
        assert w.window_kind == "daily"


class TestFakeProviderEmbed:
    def test_returns_64_dim_vector(self) -> None:
        p = FakeProvider()
        vec = p.embed("hello world")
        assert len(vec) == 64

    def test_deterministic(self) -> None:
        p = FakeProvider()
        v1 = p.embed("test string")
        v2 = p.embed("test string")
        assert v1 == v2

    def test_different_inputs_different_outputs(self) -> None:
        p = FakeProvider()
        v1 = p.embed("alpha")
        v2 = p.embed("beta")
        assert v1 != v2

    def test_values_in_range(self) -> None:
        p = FakeProvider()
        vec = p.embed("anything")
        assert all(-1.0 <= v <= 1.0 for v in vec)

    def test_embed_increments_quota(self) -> None:
        p = FakeProvider()
        p.embed("a" * 100)
        w = p.quota_window()
        assert w.tokens_used >= 1


class TestFakeProviderInteraction:
    def test_rate_limit_then_success(self) -> None:
        p = FakeProvider(fail_every=3)
        assert p.complete("1") == "fake response"
        assert p.complete("2") == "fake response"
        with pytest.raises(RateLimited):
            p.complete("3")
        assert p.complete("4") == "fake response"

    def test_both_failure_modes(self) -> None:
        p = FakeProvider(fail_every=2, unavailable_every=3)
        assert p.complete("1") == "fake response"
        with pytest.raises(RateLimited):
            p.complete("2")
        with pytest.raises(ProviderUnavailable):
            p.complete("3")
