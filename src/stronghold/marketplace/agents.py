"""Agent marketplace: publish, search, rate, and retrieve community agents.

Provides an in-memory implementation for browsing and rating agent listings.
The marketplace enforces rating bounds (1-5), prevents duplicate publishes,
and maintains running average ratings on each listing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

logger = logging.getLogger("stronghold.marketplace.agents")


@dataclass(frozen=True)
class AgentListing:
    """A published agent in the marketplace."""

    name: str
    description: str = ""
    author: str = ""
    version: str = "1.0.0"
    trust_tier: str = "t2"
    install_count: int = 0
    avg_rating: float = 0.0
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentRating:
    """A user rating for a marketplace agent."""

    agent_name: str
    user_id: str
    org_id: str
    rating: int
    comment: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class InMemoryAgentMarketplace:
    """In-memory agent marketplace.

    Stores published listings and user ratings. Supports search by
    name, description, and tags with configurable result limits.
    """

    def __init__(self) -> None:
        self._listings: dict[str, AgentListing] = {}
        self._ratings: dict[str, list[AgentRating]] = {}

    async def publish(self, listing: AgentListing) -> AgentListing:
        """Publish an agent listing to the marketplace.

        Raises ValueError if the name is empty or already published.
        """
        if not listing.name:
            msg = "Agent name is required"
            raise ValueError(msg)
        if listing.name in self._listings:
            msg = f"Agent '{listing.name}' is already published"
            raise ValueError(msg)
        self._listings[listing.name] = listing
        logger.info(
            "Agent '%s' published by %s (v%s)", listing.name, listing.author, listing.version
        )
        return listing

    async def search(
        self,
        query: str,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[AgentListing]:
        """Search listings by name, description, and tags.

        An empty query with no tag filter returns all listings (up to limit).
        """
        query_lower = query.lower().strip()
        tag_set = {t.lower() for t in tags} if tags else set()

        results: list[AgentListing] = []
        for listing in self._listings.values():
            # Tag filter: if tags specified, listing must have at least one matching tag
            if tag_set:
                listing_tags = {t.lower() for t in listing.tags}
                if not tag_set & listing_tags:
                    continue

            # Text filter: match against name or description
            if query_lower:
                name_match = query_lower in listing.name.lower()
                desc_match = query_lower in listing.description.lower()
                if not (name_match or desc_match):
                    continue

            results.append(listing)
            if len(results) >= limit:
                break

        return results

    async def rate(self, rating: AgentRating) -> AgentRating:
        """Rate a marketplace agent (1-5).

        Updates the listing's avg_rating. Raises ValueError for invalid
        ratings or unknown agents.
        """
        if rating.rating < 1 or rating.rating > 5:
            msg = "Rating must be between 1 and 5"
            raise ValueError(msg)
        if rating.agent_name not in self._listings:
            msg = f"Agent '{rating.agent_name}' not found in marketplace"
            raise ValueError(msg)

        # Store the rating
        if rating.agent_name not in self._ratings:
            self._ratings[rating.agent_name] = []
        self._ratings[rating.agent_name].append(rating)

        # Recalculate average
        agent_ratings = self._ratings[rating.agent_name]
        avg = sum(r.rating for r in agent_ratings) / len(agent_ratings)
        self._listings[rating.agent_name] = replace(
            self._listings[rating.agent_name], avg_rating=avg
        )

        logger.info(
            "Agent '%s' rated %d/5 by %s (new avg: %.1f)",
            rating.agent_name,
            rating.rating,
            rating.user_id,
            avg,
        )
        return rating

    async def get_ratings(self, agent_name: str) -> list[AgentRating]:
        """Get all ratings for an agent."""
        return list(self._ratings.get(agent_name, []))

    async def get_listing(self, agent_name: str) -> AgentListing | None:
        """Get a single agent listing by name, or None if not found."""
        return self._listings.get(agent_name)
