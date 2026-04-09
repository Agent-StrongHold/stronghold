"""Agent marketplace models and endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator

from stronghold.agents.base import Agent
from stronghold.security.auth_static import StaticKeyAuthProvider

if TYPE_CHECKING:
    from stronghold.container import Container
    from stronghold.types.auth import AuthContext

router = APIRouter(prefix="/v1/stronghold", tags=["agents"])

TRUST_TIERS = ["low", "medium", "high"]


class Review(BaseModel):
    rating: int
    comment: str
    reviewer: dict[str, str]


class AgentCreateRequest(BaseModel):
    name: str
    description: str
    strategy: str
    tools: list[str]
    capabilities: list[str] = Field(default_factory=list, description="Capabilities of the agent")
    trust_tier: str = Field(..., description="Trust tier of the agent")
    install_count: int = Field(default=0, description="Number of times installed")

    @validator("name")
    def name_must_not_be_empty(self, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v

    @validator("trust_tier")
    def trust_tier_must_be_valid(self, v: str) -> str:
        if v not in TRUST_TIERS:
            raise ValueError(f"trust_tier must be one of {TRUST_TIERS}")
        return v


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    strategy: str
    tools: list[str]
    capabilities: list[str]
    trust_tier: str
    install_count: int
    rating: float | None = None


class AgentRatingsResponse(BaseModel):
    average_rating: float
    total_reviews: int


class AgentReviewsResponse(BaseModel):
    ratings: AgentRatingsResponse
    reviews: list[Review]


@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    request: AgentCreateRequest,
    container: Container = Depends(lambda: None),
    auth: AuthContext = Depends(StaticKeyAuthProvider().authenticate),
) -> AgentResponse:
    """Create a new agent in the marketplace."""
    # Check if agent with this name already exists
    existing_agent = container.agent_registry.get_by_name(request.name)
    if existing_agent:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with name '{request.name}' already exists",
        )

    # Create the agent
    agent = Agent(
        name=request.name,
        description=request.description,
        strategy=request.strategy,
        tools=request.tools,
        capabilities=request.capabilities,
        trust_tier=request.trust_tier,
        install_count=request.install_count,
    )

    # Store the agent
    stored_agent = container.agent_registry.create(agent)

    return AgentResponse(
        id=str(stored_agent.id),
        name=stored_agent.name,
        description=stored_agent.description,
        strategy=stored_agent.strategy,
        tools=stored_agent.tools,
        capabilities=stored_agent.capabilities,
        trust_tier=stored_agent.trust_tier,
        install_count=stored_agent.install_count,
        rating=stored_agent.rating,
    )


@router.get("/agents", response_model=list[AgentResponse])
async def search_agents(
    capability: str | None = None,
    trust_tier: str | None = None,
    container: Container = Depends(lambda: None),
    auth: AuthContext = Depends(StaticKeyAuthProvider().authenticate),
) -> list[AgentResponse]:
    """Search agents by capability or trust tier."""
    agents = container.agent_registry.list_agents()

    if capability:
        agents = [agent for agent in agents if capability in agent.capabilities]

    if trust_tier:
        agents = [agent for agent in agents if agent.trust_tier == trust_tier]

    return [
        AgentResponse(
            id=str(agent.id),
            name=agent.name,
            description=agent.description,
            strategy=agent.strategy,
            tools=agent.tools,
            capabilities=agent.capabilities,
            trust_tier=agent.trust_tier,
            install_count=agent.install_count,
            rating=agent.rating,
        )
        for agent in agents
    ]


@router.get("/agents/{agent_id}/reviews", response_model=AgentReviewsResponse)
async def get_agent_reviews(
    agent_id: str,
    container: Container = Depends(lambda: None),
    auth: AuthContext = Depends(StaticKeyAuthProvider().authenticate),
) -> AgentReviewsResponse:
    """Get ratings and reviews for a specific agent."""
    agent = container.agent_registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent with id '{agent_id}' not found",
        )

    reviews = agent.reviews if agent.reviews else []

    total_reviews = len(reviews)
    average_rating = (
        sum(review["rating"] for review in reviews) / total_reviews if total_reviews > 0 else 0.0
    )

    return AgentReviewsResponse(
        ratings=AgentRatingsResponse(
            average_rating=average_rating,
            total_reviews=total_reviews,
        ),
        reviews=reviews,
    )
