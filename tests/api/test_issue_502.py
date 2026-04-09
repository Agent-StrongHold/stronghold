"""Tests for agent creation."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.agents import router as agents_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(agents_router)
    container = make_test_container()
    app.state.container = container
    return app


class TestCreateAgent:
    def test_create_agent_with_required_fields(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Code Review Assistant"
            assert data["description"] == "AI-powered code reviewer"
            assert data["strategy"] == "review"
            assert data["tools"] == ["pylint", "flake8"]
            assert data["trust_tier"] == "high"
            assert data["install_count"] == 0


class TestSearchAgentsByCapability:
    def test_search_agents_by_capability_code_review(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different capabilities
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "capabilities": ["code_review", "linting"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "capabilities": ["documentation"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "capabilities": ["code_review"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)

            # Search for agents with code_review capability
            resp = client.get(
                "/v1/stronghold/agents", params={"capability": "code_review"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with code_review capability are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Code Review Assistant" in agent_names
            assert "Code Review Expert" in agent_names
            assert "Documentation Writer" not in agent_names


class TestSearchAgentsByTrustTier:
    def test_search_agents_by_trust_tier_high(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different trust tiers
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)

            # Search for agents with high trust tier
            resp = client.get(
                "/v1/stronghold/agents", params={"trust_tier": "high"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with high trust tier are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Code Review Assistant" in agent_names
            assert "Code Review Expert" in agent_names
            assert "Documentation Writer" not in agent_names


class TestSearchAgentsByMultipleCriteria:
    def test_filter_agents_by_capability_and_trust_tier(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with various capabilities and trust tiers
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "capabilities": ["code_review", "linting"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "capabilities": ["documentation"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "capabilities": ["code_review"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent4 = {
                "name": "Security Scanner",
                "description": "Security vulnerability scanner",
                "strategy": "scan",
                "tools": ["bandit", "safety"],
                "capabilities": ["code_review", "security"],
                "trust_tier": "medium",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent4, headers=AUTH_HEADER)

            # Search for agents with capability "code_review" and trust tier "high"
            resp = client.get(
                "/v1/stronghold/agents",
                params={"capability": "code_review", "trust_tier": "high"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents matching both criteria are returned
            assert len(data) == 3
            agent_names = [agent["name"] for agent in data]
            assert "Code Review Assistant" in agent_names
            assert "Code Review Expert" in agent_names
            assert "Documentation Writer" in agent_names
            assert "Security Scanner" not in agent_names


class TestCreateAgentWithMissingFields:
    def test_create_agent_with_missing_required_fields(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Missing required fields: name, strategy, trust_tier
            payload = {
                "description": "AI-powered code reviewer",
                "tools": ["pylint", "flake8"],
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 422  # Unprocessable Entity
            data = resp.json()
            assert "detail" in data
            assert len(data["detail"]) > 0
            error_messages = [error["msg"] for error in data["detail"]]
            assert any("name" in msg.lower() for msg in error_messages)
            assert any("strategy" in msg.lower() for msg in error_messages)
            assert any("trust_tier" in msg.lower() for msg in error_messages)

    def test_create_agent_with_empty_name(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                "name": "",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 422
            data = resp.json()
            assert "detail" in data
            error_messages = [error["msg"] for error in data["detail"]]
            assert any("name" in msg.lower() for msg in error_messages)

    def test_create_agent_with_invalid_trust_tier(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                "name": "Test Agent",
                "description": "Test description",
                "strategy": "review",
                "tools": ["pylint"],
                "trust_tier": "invalid_tier",
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 422
            data = resp.json()
            assert "detail" in data
            error_messages = [error["msg"] for error in data["detail"]]
            assert any("trust_tier" in msg.lower() for msg in error_messages)


class TestGetAgentRatingsAndReviews:
    def test_get_agent_ratings_and_reviews(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create an agent
            agent_payload = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            create_resp = client.post(
                "/v1/stronghold/agents", json=agent_payload, headers=AUTH_HEADER
            )
            assert create_resp.status_code == 200
            agent_data = create_resp.json()
            agent_id = agent_data["id"]

            # Add reviews to the agent
            review1 = {
                "rating": 5,
                "comment": "Excellent agent, very helpful!",
                "reviewer": {"name": "Alice", "id": "user-123"},
            }
            review2 = {
                "rating": 4,
                "comment": "Good overall performance",
                "reviewer": {"name": "Bob", "id": "user-456"},
            }
            review3 = {
                "rating": 3,
                "comment": "Could improve response time",
                "reviewer": {"name": "Charlie", "id": "user-789"},
            }

            # Add reviews to the agent (implementation would add these to the agent's reviews list)
            container = app.state.container
            agent = container.agent_registry.get_agent(agent_id)
            agent.reviews = [review1, review2, review3]

            # Retrieve the agent's ratings and reviews
            resp = client.get(f"/v1/stronghold/agents/{agent_id}/reviews", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()

            # Verify the response includes all ratings and reviews
            assert "ratings" in data
            assert "reviews" in data
            assert len(data["reviews"]) == 3

            # Verify each review has the required fields
            for review in data["reviews"]:
                assert "rating" in review
                assert "comment" in review
                assert "reviewer" in review
                assert "name" in review["reviewer"]
                assert "id" in review["reviewer"]

            # Verify ratings summary
            assert "average_rating" in data["ratings"]
            assert "total_reviews" in data["ratings"]
            assert data["ratings"]["total_reviews"] == 3
            assert data["ratings"]["average_rating"] == 4.0  # (5 + 4 + 3) / 3


class TestAgentCreationWithAllRequiredFields:
    def test_create_agent_with_all_required_fields(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            payload = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()

            # Verify all required fields are present and correct
            assert data["name"] == "Code Review Assistant"
            assert data["description"] == "AI-powered code reviewer"
            assert data["strategy"] == "review"
            assert data["tools"] == ["pylint", "flake8"]
            assert data["trust_tier"] == "high"
            assert data["install_count"] == 0
            assert "id" in data
            assert isinstance(data["id"], str)


class TestSearchAgentsByCapability:
    def test_search_agents_by_capability_code_review(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different capabilities
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "capabilities": ["code_review", "linting"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "capabilities": ["documentation"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "capabilities": ["code_review"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)

            # Search for agents with code_review capability
            resp = client.get(
                "/v1/stronghold/agents", params={"capability": "code_review"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with code_review capability are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Code Review Assistant" in agent_names
            assert "Code Review Expert" in agent_names
            assert "Documentation Writer" not in agent_names


class TestSearchAgentsByTrustTier:
    def test_search_agents_by_trust_tier_high(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different trust tiers
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)

            # Search for agents with high trust tier
            resp = client.get(
                "/v1/stronghold/agents", params={"trust_tier": "high"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with high trust tier are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Code Review Assistant" in agent_names
            assert "Code Review Expert" in agent_names
            assert "Documentation Writer" not in agent_names


class TestSearchAgentsByTrustTier:
    def test_search_agents_by_trust_tier_low(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different trust tiers
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "trust_tier": "low",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent4 = {
                "name": "Security Scanner",
                "description": "Security vulnerability scanner",
                "strategy": "scan",
                "tools": ["bandit", "safety"],
                "trust_tier": "low",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent4, headers=AUTH_HEADER)

            # Search for agents with low trust tier
            resp = client.get(
                "/v1/stronghold/agents", params={"trust_tier": "low"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with low trust tier are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Documentation Writer" in agent_names
            assert "Security Scanner" in agent_names
            assert "Code Review Assistant" not in agent_names
            assert "Code Review Expert" not in agent_names


class TestAgentCreationWithMissingRequiredFields:
    def test_create_agent_with_missing_required_fields_fails(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Attempt to create agent with missing required fields
            payload = {
                "description": "AI-powered code reviewer",
                "tools": ["pylint", "flake8"],
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)

            # Should fail with 422 Unprocessable Entity
            assert resp.status_code == 422

            data = resp.json()
            assert "detail" in data
            assert len(data["detail"]) > 0

            # Verify error messages mention missing fields
            error_messages = [error["msg"] for error in data["detail"]]
            assert any("field required" in msg.lower() for msg in error_messages)

            # Verify agent was not created
            container = app.state.container
            assert len(container.agent_registry.list_agents()) == 0


class TestAgentReviewsEndpoint:
    def test_get_agent_reviews_endpoint_returns_all_reviews(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create an agent
            agent_payload = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            create_resp = client.post(
                "/v1/stronghold/agents", json=agent_payload, headers=AUTH_HEADER
            )
            assert create_resp.status_code == 200
            agent_data = create_resp.json()
            agent_id = agent_data["id"]

            # Add reviews to the agent
            review1 = {
                "rating": 5,
                "comment": "Excellent agent, very helpful!",
                "reviewer": {"name": "Alice", "id": "user-123"},
            }
            review2 = {
                "rating": 4,
                "comment": "Good overall performance",
                "reviewer": {"name": "Bob", "id": "user-456"},
            }
            review3 = {
                "rating": 3,
                "comment": "Could improve response time",
                "reviewer": {"name": "Charlie", "id": "user-789"},
            }

            # Add reviews to the agent (implementation would add these to the agent's reviews list)
            container = app.state.container
            agent = container.agent_registry.get_agent(agent_id)
            agent.reviews = [review1, review2, review3]

            # Retrieve the agent's reviews
            resp = client.get(f"/v1/stronghold/agents/{agent_id}/reviews", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()

            # Verify the response includes all reviews
            assert "reviews" in data
            assert len(data["reviews"]) == 3

            # Verify each review has the required fields
            for review in data["reviews"]:
                assert "rating" in review
                assert "comment" in review
                assert "reviewer" in review
                assert "name" in review["reviewer"]
                assert "id" in review["reviewer"]


class TestAgentCreationScenario:
    def test_create_agent_with_all_required_fields_and_retrieve_by_name(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create a new agent with all required fields
            payload = {
                "name": "Data Analyst",
                "description": "Analyzes datasets",
                "strategy": "ML",
                "tools": ["pandas", "numpy"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create the agent
            create_resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)
            assert create_resp.status_code == 200
            created_agent = create_resp.json()

            # Verify all fields are saved correctly
            assert created_agent["name"] == "Data Analyst"
            assert created_agent["description"] == "Analyzes datasets"
            assert created_agent["strategy"] == "ML"
            assert created_agent["tools"] == ["pandas", "numpy"]
            assert created_agent["trust_tier"] == "high"
            assert created_agent["install_count"] == 0
            assert "id" in created_agent
            assert isinstance(created_agent["id"], str)

            # Retrieve the agent by name through search
            search_resp = client.get(
                "/v1/stronghold/agents", params={"name": "Data Analyst"}, headers=AUTH_HEADER
            )
            assert search_resp.status_code == 200
            search_results = search_resp.json()

            # Verify the agent is retrievable
            assert len(search_results) == 1
            retrieved_agent = search_results[0]
            assert retrieved_agent["name"] == "Data Analyst"
            assert retrieved_agent["description"] == "Analyzes datasets"
            assert retrieved_agent["strategy"] == "ML"
            assert retrieved_agent["tools"] == ["pandas", "numpy"]
            assert retrieved_agent["trust_tier"] == "high"
            assert retrieved_agent["install_count"] == 0


class TestSearchAgentsByToolCapability:
    def test_search_agents_by_tool_capability(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different tool capabilities
            agent1 = {
                "name": "Data Analyst",
                "description": "Analyzes datasets with pandas",
                "strategy": "ML",
                "tools": ["pandas", "scikit-learn"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Visualization Expert",
                "description": "Creates visualizations",
                "strategy": "visualize",
                "tools": ["numpy", "matplotlib"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "ML Engineer",
                "description": "Machine learning engineer",
                "strategy": "ML",
                "tools": ["pandas", "numpy", "scikit-learn"],
                "trust_tier": "high",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)

            # Search for agents with pandas tool capability
            resp = client.get(
                "/v1/stronghold/agents", params={"capability": "pandas"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents containing "pandas" in their tools are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Data Analyst" in agent_names
            assert "ML Engineer" in agent_names
            assert "Visualization Expert" not in agent_names


class TestSearchAgentsByTrustTier:
    def test_search_agents_by_trust_tier_medium(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create agents with different trust tiers
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            agent3 = {
                "name": "Code Review Expert",
                "description": "Specialized code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8", "mypy"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent4 = {
                "name": "Security Scanner",
                "description": "Security vulnerability scanner",
                "strategy": "scan",
                "tools": ["bandit", "safety"],
                "trust_tier": "medium",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent3, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent4, headers=AUTH_HEADER)

            # Search for agents with medium trust tier
            resp = client.get(
                "/v1/stronghold/agents", params={"trust_tier": "medium"}, headers=AUTH_HEADER
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify only agents with medium trust tier are returned
            assert len(data) == 2
            agent_names = [agent["name"] for agent in data]
            assert "Documentation Writer" in agent_names
            assert "Security Scanner" in agent_names
            assert "Code Review Assistant" not in agent_names
            assert "Code Review Expert" not in agent_names


class TestAgentRatingsAndReviewsWithExactCriteria:
    def test_retrieve_agent_ratings_and_reviews_with_exact_criteria(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create an agent named "Data Analyst"
            agent_payload = {
                "name": "Data Analyst",
                "description": "Analyzes datasets and provides insights",
                "strategy": "ML",
                "tools": ["pandas", "numpy", "matplotlib"],
                "trust_tier": "high",
                "install_count": 0,
            }
            create_resp = client.post(
                "/v1/stronghold/agents", json=agent_payload, headers=AUTH_HEADER
            )
            assert create_resp.status_code == 200
            agent_data = create_resp.json()
            agent_id = agent_data["id"]

            # Add 5 reviews with average rating 4.2
            reviews = [
                {
                    "rating": 5,
                    "comment": "Excellent performance!",
                    "reviewer": {"name": "User1", "id": "user-001"},
                },
                {
                    "rating": 4,
                    "comment": "Very good, minor improvements needed",
                    "reviewer": {"name": "User2", "id": "user-002"},
                },
                {
                    "rating": 4,
                    "comment": "Solid work",
                    "reviewer": {"name": "User3", "id": "user-003"},
                },
                {
                    "rating": 4,
                    "comment": "Reliable and fast",
                    "reviewer": {"name": "User4", "id": "user-004"},
                },
                {
                    "rating": 4,
                    "comment": "Good overall",
                    "reviewer": {"name": "User5", "id": "user-005"},
                },
            ]

            # Add reviews to the agent
            container = app.state.container
            agent = container.agent_registry.get_agent(agent_id)
            agent.reviews = reviews

            # Retrieve the agent's ratings and reviews
            resp = client.get(f"/v1/stronghold/agents/{agent_id}/reviews", headers=AUTH_HEADER)
            assert resp.status_code == 200
            data = resp.json()

            # Verify the response includes the average rating 4.2
            assert "ratings" in data
            assert "average_rating" in data["ratings"]
            assert data["ratings"]["average_rating"] == 4.2

            # Verify the response includes all 5 reviews
            assert "reviews" in data
            assert len(data["reviews"]) == 5

            # Verify each review has the required fields
            for review in data["reviews"]:
                assert "rating" in review
                assert "comment" in review
                assert "reviewer" in review
                assert "name" in review["reviewer"]
                assert "id" in review["reviewer"]


class TestAgentCreationWithMissingNameField:
    def test_create_agent_with_missing_name_field_fails_with_validation_error(
        self, app: FastAPI
    ) -> None:
        with TestClient(app) as client:
            # Attempt to create agent with missing name field
            payload = {
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "high",
                "install_count": 0,
            }
            resp = client.post("/v1/stronghold/agents", json=payload, headers=AUTH_HEADER)

            # Should fail with 422 Unprocessable Entity
            assert resp.status_code == 422

            data = resp.json()
            assert "detail" in data
            assert len(data["detail"]) > 0

            # Verify error message indicates name is required
            error_messages = [error["msg"] for error in data["detail"]]
            assert any(
                "name" in msg.lower() and "required" in msg.lower() for msg in error_messages
            )

            # Verify agent was not created
            container = app.state.container
            assert len(container.agent_registry.list_agents()) == 0


class TestUpdateAgentTrustTier:
    def test_update_agent_trust_tier(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create an agent with medium trust tier
            agent_payload = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "trust_tier": "medium",
                "install_count": 0,
            }
            create_resp = client.post(
                "/v1/stronghold/agents", json=agent_payload, headers=AUTH_HEADER
            )
            assert create_resp.status_code == 200
            agent_data = create_resp.json()
            agent_id = agent_data["id"]

            # Verify initial trust tier is medium
            assert agent_data["trust_tier"] == "medium"

            # Update the agent's trust tier to high
            update_payload = {"trust_tier": "high"}
            update_resp = client.patch(
                f"/v1/stronghold/agents/{agent_id}", json=update_payload, headers=AUTH_HEADER
            )
            assert update_resp.status_code == 200
            updated_agent_data = update_resp.json()

            # Verify the trust tier was updated to high
            assert updated_agent_data["trust_tier"] == "high"

            # Verify subsequent queries reflect the updated tier
            get_resp = client.get(f"/v1/stronghold/agents/{agent_id}", headers=AUTH_HEADER)
            assert get_resp.status_code == 200
            retrieved_agent_data = get_resp.json()
            assert retrieved_agent_data["trust_tier"] == "high"


class TestSearchAgentsWithNonExistentCapability:
    def test_search_agents_with_non_existent_capability(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Create some agents with various capabilities
            agent1 = {
                "name": "Code Review Assistant",
                "description": "AI-powered code reviewer",
                "strategy": "review",
                "tools": ["pylint", "flake8"],
                "capabilities": ["code_review", "linting"],
                "trust_tier": "high",
                "install_count": 0,
            }
            agent2 = {
                "name": "Documentation Writer",
                "description": "Generates documentation",
                "strategy": "write",
                "tools": ["sphinx"],
                "capabilities": ["documentation"],
                "trust_tier": "medium",
                "install_count": 0,
            }

            # Create all agents
            client.post("/v1/stronghold/agents", json=agent1, headers=AUTH_HEADER)
            client.post("/v1/stronghold/agents", json=agent2, headers=AUTH_HEADER)

            # Search for agents with a non-existent capability
            resp = client.get(
                "/v1/stronghold/agents",
                params={"capability": "nonexistent_tool"},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            data = resp.json()

            # Verify the results are empty
            assert len(data) == 0
