"""UserPoints model for tracking user XP, level, and activity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserPoints:
    """Model for tracking user points and activity."""

    user_id: str
    total_xp: int
    level: int
    issues_solved: int
    reviews: int
    streaks: int

    def add_xp(self, amount: int) -> None:
        """Add XP to the user's total."""
        if amount < 0:
            raise ValueError("XP cannot be negative")
        self.total_xp += amount
        self._update_level()

    def _update_level(self) -> None:
        """Update level based on total XP."""
        self.level = self.total_xp // 100

    def update_xp(self, amount: int) -> None:
        """Update XP and recalculate level."""
        if amount < 0:
            raise ValueError("XP cannot be negative")
        self.total_xp += amount
        self._update_level()
