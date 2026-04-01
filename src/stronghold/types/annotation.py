"""Annotation types for conversation tagging, rating, and notes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Annotation:
    """A user-created annotation on a conversation session.

    Supports tagging, 1-5 star rating, and free-text notes.
    All annotations are org-scoped for tenant isolation.
    """

    id: str = ""
    session_id: str = ""
    user_id: str = ""
    org_id: str = ""
    tags: list[str] = field(default_factory=list)
    rating: int | None = None  # 1-5 stars, None if not rated
    note: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
