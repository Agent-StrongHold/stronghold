"""Tests for UserPoints model."""

from __future__ import annotations

from stronghold.types.user_points import UserPoints


class TestUserPointsModel:
    def test_model_has_all_required_fields_populated(self) -> None:
        # Given a new UserPoints model is being created
        user_points = UserPoints(
            user_id="user-123",
            total_xp=1000,
            level=5,
            issues_solved=20,
            reviews=5,
            streaks=3,
        )

        # Then the model should have all required fields populated correctly
        assert user_points.user_id == "user-123"
        assert user_points.total_xp == 1000
        assert user_points.level == 5
        assert user_points.issues_solved == 20
        assert user_points.reviews == 5
        assert user_points.streaks == 3

    def test_xp_and_level_update(self) -> None:
        # Given an existing UserPoints record with total_xp = 100 and level = 5
        user_points = UserPoints(
            user_id="user-456",
            total_xp=100,
            level=5,
            issues_solved=10,
            reviews=2,
            streaks=1,
        )

        # When XP is updated by adding 50 points
        user_points.total_xp += 50

        # Then total_xp should be 150 and level should be recalculated based on XP thresholds
        assert user_points.total_xp == 150
        assert user_points.level == 6
