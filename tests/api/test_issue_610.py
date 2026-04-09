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
        llm_client=None,
        embedding_client=None,
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
