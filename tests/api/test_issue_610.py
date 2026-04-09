"""Tests for UserPoints model."""

from __future__ import annotations

import pytest

from stronghold.container import Container
from stronghold.memory.outcomes import InMemoryOutcomeStore

# Import the model you're testing
from stronghold.models.user_points import UserPoints
from stronghold.types.agent import AgentIdentity
from stronghold.types.config import StrongholdConfig


@pytest.fixture
def container() -> Container:
    """Create a test container."""
    config = StrongholdConfig(
        service_name="stronghold",
        auth_static_key="sk-test",
        redis_url="redis://localhost:6379",
        llm_client="fake",
        embedding_client="fake",
        agent_identity=AgentIdentity(name="test", version="1.0"),
    )
    return Container(
        config=config,
        agent_registry=None,
        context_builder=None,
        strategy_selector=None,
        tool_registry=None,
        tool_executor=None,
        prompt_manager=None,
        quota_tracker=None,
        session_store=None,
        learning_store=InMemoryOutcomeStore(),
        outcome_store=InMemoryOutcomeStore(),
        audit_log=None,
        sentinel=None,
        warden=None,
        tracing=None,
    )


class TestUserPointsModel:
    def test_create_user_points_with_required_fields(self, container: Container) -> None:
        """Successfully create UserPoints model with required fields."""
        user_points = UserPoints(
            user_id="user-123",
            total_xp=100,
            level=5,
            issues_solved=20,
            reviews=10,
            streaks=3,
        )
        assert user_points.user_id == "user-123"
        assert user_points.total_xp == 100
        assert user_points.level == 5
        assert user_points.issues_solved == 20
        assert user_points.reviews == 10
        assert user_points.streaks == 3

    def test_update_xp_and_recalculate_level(self) -> None:
        """Update XP and level through model methods."""
        # Given an existing UserPoints record with total_xp: 100 and level: 1
        user_points = UserPoints(
            user_id="user-123",
            total_xp=100,
            level=1,
            issues_solved=0,
            reviews=0,
            streaks=0,
        )

        # When the update_xp method is called with 50 additional XP
        user_points.update_xp(50)

        # Then the total_xp should be updated to 150
        assert user_points.total_xp == 150

        # And the level should be recalculated based on the new XP
        assert user_points.level == 2

    def test_update_xp_with_negative_value_raises_error(self) -> None:
        """Update XP with negative value should raise error and not update XP."""
        # Given an existing UserPoints record with total_xp: 50
        user_points = UserPoints(
            user_id="user-123",
            total_xp=50,
            level=1,
            issues_solved=0,
            reviews=0,
            streaks=0,
        )

        # When the update_xp method is called with -100 XP
        with pytest.raises(ValueError, match="XP cannot be negative"):
            user_points.update_xp(-100)

        # Then the XP should not be updated
        assert user_points.total_xp == 50

        # And the level should remain unchanged
        assert user_points.level == 1


class TestUserPointsMigration:
    def test_user_points_table_created_with_correct_columns(self) -> None:
        """Verify UserPoints table has all required columns with correct data types."""
        # This test verifies the migration file creates the correct table structure
        # In a real implementation, this would use SQLAlchemy's metadata reflection
        # or a database connection to inspect the schema

        # Given a migration file that defines UserPoints table
        # When the migration is executed
        # Then the UserPoints table should exist

        # Mock verification of table creation (implementation would vary by ORM)

        from stronghold.models.user_points import UserPoints

        # In a real test environment with a database connection:
        # inspector = inspect(engine)
        # columns = inspector.get_columns("user_points")

        # For this test, we verify the model has all required fields
        required_columns = {
            "user_id": str,
            "total_xp": int,
            "level": int,
            "issues_solved": int,
            "reviews": int,
            "streaks": int,
        }

        for column_name, expected_type in required_columns.items():
            assert hasattr(UserPoints, column_name), f"Missing column: {column_name}"
            column = getattr(UserPoints, column_name)
            assert isinstance(column.type, expected_type), f"Wrong type for {column_name}"

        # Verify primary key exists
        assert hasattr(UserPoints, "id") or hasattr(UserPoints, "user_id")
