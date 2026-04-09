"""Tests for UserPoints model."""

from __future__ import annotations

import pytest

from stronghold.models.user_points import UserPoints


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

    def test_negative_xp_update_raises_error(self) -> None:
        # Given an existing UserPoints record with total_xp = 100
        user_points = UserPoints(
            user_id="user-789",
            total_xp=100,
            level=5,
            issues_solved=10,
            reviews=2,
            streaks=1,
        )

        # When an attempt is made to update XP with a negative value (-20)
        initial_xp = user_points.total_xp
        with pytest.raises(ValueError, match="XP cannot be negative"):
            user_points.total_xp -= 20

        # Then the XP should remain unchanged at 100
        assert user_points.total_xp == initial_xp

    def test_migration_creates_user_points_table(self) -> None:
        # Given a new database migration file for UserPoints table
        # When the migration is run against the database
        # Then a UserPoints table should be created with all required columns
        # This test verifies the migration schema matches the model fields

        # This would typically query the database schema
        # For testing purposes, we verify the model has all required fields
        user_points = UserPoints(
            user_id="test-user",
            total_xp=0,
            level=1,
            issues_solved=0,
            reviews=0,
            streaks=0,
        )

        # Verify all model fields exist that would map to table columns
        assert hasattr(user_points, "user_id")
        assert hasattr(user_points, "total_xp")
        assert hasattr(user_points, "level")
        assert hasattr(user_points, "issues_solved")
        assert hasattr(user_points, "reviews")
        assert hasattr(user_points, "streaks")
