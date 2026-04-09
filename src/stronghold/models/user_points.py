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

    def __post_init__(self) -> None:
        """Initialize level if not provided."""
        if self.level == 0:
            self._update_level()

    def add_xp(self, amount: int) -> None:
        """Add XP to the user's total."""
        if amount < 0:
            raise ValueError("XP cannot be negative")
        self.total_xp += amount
        self._update_level()

    def _update_level(self) -> None:
        """Update level based on total XP."""
        self.level = max(1, self.total_xp // 100)

    def update_xp(self, amount: int) -> None:
        """Update XP and recalculate level."""
        if amount < 0:
            raise ValueError("XP cannot be negative")
        self.total_xp += amount
        self._update_level()

    @classmethod
    def create(
        cls,
        user_id: str,
        total_xp: int = 0,
        issues_solved: int = 0,
        reviews: int = 0,
        streaks: int = 0,
    ) -> UserPoints:
        """Create a new UserPoints instance with calculated level."""
        level = max(1, total_xp // 100)
        return cls(
            user_id=user_id,
            total_xp=total_xp,
            level=level,
            issues_solved=issues_solved,
            reviews=reviews,
            streaks=streaks,
        )
