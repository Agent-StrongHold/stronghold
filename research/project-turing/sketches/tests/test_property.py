"""Property-based tests using Hypothesis for core invariants.

Spec: Test structural invariants that must hold for all inputs:
- guess_node_kind() is total: never raises, always returns a NodeKind
- clamp_weight() always returns within tier bounds
- FreeTierWindow.headroom is never negative
- Repo insert → get round-trips preserve identity fields

Acceptance criteria:
- 100+ generated inputs per property
- No crashes, no assertion failures
- Covers boundary conditions (empty strings, extreme floats, etc.)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from turing.repo import Repo
from turing.self_model import NodeKind, guess_node_kind
from turing.tiers import WEIGHT_BOUNDS, clamp_weight
from turing.types import EpisodicMemory, MemoryTier, SourceKind


class TestGuessNodeKindProperties:
    @given(st.text(min_size=0, max_size=100))
    @settings(max_examples=200)
    def test_never_raises(self, node_id: str) -> None:
        result = guess_node_kind(node_id)
        assert isinstance(result, NodeKind)

    @given(st.text(min_size=0, max_size=100))
    @settings(max_examples=200)
    def test_always_returns_valid_enum(self, node_id: str) -> None:
        result = guess_node_kind(node_id)
        assert result in set(NodeKind)

    @given(st.from_regex(r"facet:.*", fullmatch=True))
    @settings(max_examples=50)
    def test_facet_prefix_always_personality_facet(self, node_id: str) -> None:
        assert guess_node_kind(node_id) == NodeKind.PERSONALITY_FACET

    @given(st.from_regex(r"passion\d{0,10}", fullmatch=True))
    @settings(max_examples=50)
    def test_passion_prefix(self, node_id: str) -> None:
        assert guess_node_kind(node_id) == NodeKind.PASSION


class TestClampWeightProperties:
    @given(
        tier=st.sampled_from(list(MemoryTier)),
        weight=st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        delta=st.floats(min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_result_always_within_bounds(
        self, tier: MemoryTier, weight: float, delta: float
    ) -> None:
        result = clamp_weight(tier, weight - delta)
        lo, hi = WEIGHT_BOUNDS[tier]
        assert lo <= result <= hi

    @given(
        tier=st.sampled_from(list(MemoryTier)),
        weight=st.floats(min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_idempotent(self, tier: MemoryTier, weight: float) -> None:
        first = clamp_weight(tier, weight)
        second = clamp_weight(tier, first)
        assert first == second


class TestRepoRoundTripProperties:
    @given(
        content=st.text(min_size=1, max_size=200),
        weight=st.floats(min_value=0.11, max_value=0.49, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_insert_get_preserves_content(self, content: str, weight: float) -> None:
        repo = Repo(None)
        try:
            m = EpisodicMemory(
                memory_id=f"prop-{content[:20]}",
                self_id="test-self",
                tier=MemoryTier.OBSERVATION,
                source=SourceKind.I_DID,
                content=content,
                weight=weight,
            )
            repo.insert(m)
            retrieved = repo.get(m.memory_id)
            assert retrieved is not None
            assert retrieved.content == content
            assert retrieved.self_id == "test-self"
            assert retrieved.memory_id == m.memory_id
        finally:
            repo.close()

    @given(
        tier=st.sampled_from(
            [
                t
                for t in MemoryTier
                if t
                not in (
                    MemoryTier.WISDOM,
                    MemoryTier.REGRET,
                    MemoryTier.ACCOMPLISHMENT,
                    MemoryTier.AFFIRMATION,
                )
            ]
        ),
        source=st.sampled_from(list(SourceKind)),
        content=st.text(min_size=1, max_size=100),
        weight_offset=st.floats(min_value=0.01, max_value=0.4, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_insert_find_by_tier(
        self, tier: MemoryTier, source: SourceKind, content: str, weight_offset: float
    ) -> None:
        repo = Repo(None)
        try:
            lo, hi = WEIGHT_BOUNDS[tier]
            weight = lo + weight_offset * (hi - lo)
            m = EpisodicMemory(
                memory_id=f"find-{tier.value}-{source.value}",
                self_id="test-self",
                tier=tier,
                source=source,
                content=content,
                weight=weight,
            )
            repo.insert(m)
            found = list(repo.find(self_id="test-self", tier=tier))
            assert any(f.memory_id == m.memory_id for f in found)
        finally:
            repo.close()


class TestFreeTierWindowProperties:
    @given(
        allowed=st.integers(min_value=0, max_value=1_000_000),
        used=st.integers(min_value=0, max_value=2_000_000),
    )
    @settings(max_examples=200)
    def test_headroom_never_negative(self, allowed: int, used: int) -> None:
        from turing.runtime.providers.base import FreeTierWindow

        window = FreeTierWindow(
            provider="test",
            window_kind="rpm",
            window_started_at=datetime.now(UTC),
            window_duration=__import__("datetime").timedelta(seconds=60),
            tokens_allowed=allowed,
            tokens_used=used,
        )
        assert window.headroom >= 0
