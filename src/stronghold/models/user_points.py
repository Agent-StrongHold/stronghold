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

    def add_xp(self, amount: int) -> None:
        """Add XP to the user's total."""
        self.total_xp += amount

    def level_up(self) -> None:
        """Increment the user's level by 1."""
        self.level += 1
