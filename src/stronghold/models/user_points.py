"""UserPoints model to track XP, level, and points breakdown."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserPoints:
    """Model representing user points and progress."""

    user_id: str
    total_xp: int
    level: int
    issues_solved: int
    reviews: int
    streaks: int

    def __post_init__(self) -> None:
        """Validate that XP is not negative after initialization."""
        if self.total_xp < 0:
            raise ValueError("XP cannot be negative")
        self._update_level()

    def add_xp(self, amount: int) -> None:
        """Add XP to the user's total."""
        if amount < 0:
            raise ValueError("XP cannot be negative")
        self.total_xp += amount
        self._update_level()

    def _update_level(self) -> None:
        """Update the level based on total XP."""
        # Simple level calculation: level = total_xp // 100
        self.level = max(1, self.total_xp // 100)

    def increment_issues_solved(self, count: int = 1) -> None:
        """Increment the issues solved count."""
        self.issues_solved += count

    def increment_reviews(self, count: int = 1) -> None:
        """Increment the reviews count."""
        self.reviews += count

    def increment_streaks(self, count: int = 1) -> None:
        """Increment the streaks count."""
        self.streaks += count
