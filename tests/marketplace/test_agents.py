"""Tests for agent marketplace — browse, rate, install community agents."""

from __future__ import annotations

import pytest

from stronghold.marketplace.agents import (
    AgentListing,
    AgentRating,
    InMemoryAgentMarketplace,
)


@pytest.fixture
def marketplace() -> InMemoryAgentMarketplace:
    """Fresh marketplace instance for each test."""
    return InMemoryAgentMarketplace()


def _sample_listing(**overrides: object) -> AgentListing:
    """Build a sample AgentListing with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "code-reviewer",
        "description": "Reviews code for quality and security issues",
        "author": "stronghold-team",
        "version": "1.0.0",
        "trust_tier": "t2",
        "install_count": 0,
        "avg_rating": 0.0,
        "tags": ("code", "review", "security"),
    }
    defaults.update(overrides)
    return AgentListing(**defaults)  # type: ignore[arg-type]


def _sample_rating(**overrides: object) -> AgentRating:
    """Build a sample AgentRating with sensible defaults."""
    defaults: dict[str, object] = {
        "agent_name": "code-reviewer",
        "user_id": "user-1",
        "org_id": "org-1",
        "rating": 4,
        "comment": "Works great!",
    }
    defaults.update(overrides)
    return AgentRating(**defaults)  # type: ignore[arg-type]


# ── Publish ──────────────────────────────────────────────────────────


class TestPublish:
    """Tests for publishing agent listings."""

    async def test_publish_returns_listing(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        listing = _sample_listing()
        result = await marketplace.publish(listing)
        assert result.name == "code-reviewer"
        assert result.author == "stronghold-team"
        assert result.version == "1.0.0"

    async def test_publish_duplicate_raises(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        listing = _sample_listing()
        await marketplace.publish(listing)
        with pytest.raises(ValueError, match="already published"):
            await marketplace.publish(listing)

    async def test_publish_empty_name_raises(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        listing = _sample_listing(name="")
        with pytest.raises(ValueError, match="name.*required"):
            await marketplace.publish(listing)


# ── Search ───────────────────────────────────────────────────────────


class TestSearch:
    """Tests for searching the marketplace."""

    async def test_search_by_name(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing(name="code-reviewer"))
        await marketplace.publish(
            _sample_listing(name="doc-writer", description="Writes documentation")
        )
        results = await marketplace.search("code")
        assert len(results) == 1
        assert results[0].name == "code-reviewer"

    async def test_search_by_description(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(
            _sample_listing(name="sec-scanner", description="Scans for vulnerabilities")
        )
        results = await marketplace.search("vulnerabilities")
        assert len(results) == 1
        assert results[0].name == "sec-scanner"

    async def test_search_by_tags(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(
            _sample_listing(name="agent-a", tags=("python", "testing"))
        )
        await marketplace.publish(
            _sample_listing(name="agent-b", tags=("rust", "systems"))
        )
        results = await marketplace.search("", tags=["python"])
        assert len(results) == 1
        assert results[0].name == "agent-a"

    async def test_search_empty_query_returns_all(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing(name="agent-1"))
        await marketplace.publish(_sample_listing(name="agent-2"))
        await marketplace.publish(_sample_listing(name="agent-3"))
        results = await marketplace.search("")
        assert len(results) == 3

    async def test_search_respects_limit(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        for i in range(10):
            await marketplace.publish(_sample_listing(name=f"agent-{i}"))
        results = await marketplace.search("", limit=3)
        assert len(results) == 3

    async def test_search_no_match_returns_empty(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing(name="code-reviewer"))
        results = await marketplace.search("nonexistent-xyz")
        assert results == []


# ── Rate ─────────────────────────────────────────────────────────────


class TestRate:
    """Tests for rating agents."""

    async def test_rate_valid(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing())
        rating = _sample_rating(rating=5)
        result = await marketplace.rate(rating)
        assert result.rating == 5
        assert result.agent_name == "code-reviewer"

    async def test_rate_updates_avg_rating(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing())
        await marketplace.rate(_sample_rating(user_id="u1", rating=4))
        await marketplace.rate(_sample_rating(user_id="u2", rating=2))
        listing = await marketplace.get_listing("code-reviewer")
        assert listing is not None
        assert listing.avg_rating == pytest.approx(3.0)

    async def test_rate_invalid_range_raises(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing())
        with pytest.raises(ValueError, match="between 1 and 5"):
            await marketplace.rate(_sample_rating(rating=0))
        with pytest.raises(ValueError, match="between 1 and 5"):
            await marketplace.rate(_sample_rating(rating=6))

    async def test_rate_unknown_agent_raises(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        rating = _sample_rating(agent_name="nonexistent")
        with pytest.raises(ValueError, match="not found"):
            await marketplace.rate(rating)


# ── Get ratings ──────────────────────────────────────────────────────


class TestGetRatings:
    """Tests for retrieving ratings."""

    async def test_get_ratings_returns_all(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing())
        await marketplace.rate(_sample_rating(user_id="u1", rating=5))
        await marketplace.rate(_sample_rating(user_id="u2", rating=3))
        ratings = await marketplace.get_ratings("code-reviewer")
        assert len(ratings) == 2
        assert {r.user_id for r in ratings} == {"u1", "u2"}

    async def test_get_ratings_empty(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        ratings = await marketplace.get_ratings("nonexistent")
        assert ratings == []


# ── Get listing ──────────────────────────────────────────────────────


class TestGetListing:
    """Tests for retrieving a single listing."""

    async def test_get_listing_exists(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        await marketplace.publish(_sample_listing())
        listing = await marketplace.get_listing("code-reviewer")
        assert listing is not None
        assert listing.name == "code-reviewer"

    async def test_get_listing_not_found(
        self, marketplace: InMemoryAgentMarketplace
    ) -> None:
        listing = await marketplace.get_listing("nonexistent")
        assert listing is None
