"""Agent marketplace models and endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from stronghold.agents.base import Agent
from stronghold.security.auth_static import StaticKeyAuthProvider

if TYPE_CHECKING:
    from stronghold.container import Container
    from stronghold.types.auth import AuthContext

router = APIRouter(prefix="/v1/stronghold", tags=["agents"])


class AgentCreateRequest(BaseModel):
    name: str
    description: str
    strategy: str
    tools: list[str]
    trust_tier: str = Field(..., description="Trust tier of the agent")
    install_count: int = Field(default=0, description="Number of times installed")


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    strategy: str
    tools: list[str]
    trust_tier: str
    install_count: int
    rating: float | None = None


@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_200_OK)
async def create_agent(
    request: AgentCreateRequest,
    container: Container = Depends(lambda: None),
    auth: AuthContext = Depends(StaticKeyAuthProvider().authenticate),
) -> AgentResponse:
    """Create a new agent in the marketplace."""
    # Check if agent with this name already exists
    existing_agent = container.agents_store.get_by_name(request.name)
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
        trust_tier=request.trust_tier,
        install_count=request.install_count,
    )

    # Store the agent
    stored_agent = container.agents_store.create(agent)

    return AgentResponse(
        id=str(stored_agent.id),
        name=stored_agent.name,
        description=stored_agent.description,
        strategy=stored_agent.strategy,
        tools=stored_agent.tools,
        trust_tier=stored_agent.trust_tier,
        install_count=stored_agent.install_count,
        rating=stored_agent.rating,
    )
