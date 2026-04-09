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
