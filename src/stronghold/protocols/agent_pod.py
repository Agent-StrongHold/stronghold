"""Agent Pod Protocol - Router to Agent Pod communication.

Defines contracts for:
- AgentTask: Request from router to agent pod
- AgentResult: Response from agent pod to router
- AgentPodProtocol: Interface for agent pod implementations

Version: 1.0.0
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Protocol, Any
from enum import StrEnum


class ExecutionMode(StrEnum):
    """How much effort to put into a request."""

    BEST_EFFORT = "best_effort"
    PERSISTENT = "persistent"
    SUPERVISED = "supervised"


@dataclass
class AgentTask:
    """Request from router to agent pod."""

    task_id: str
    user_id: str
    org_id: str
    messages: list[dict]
    agent_type: str
    session_id: str | None = None
    model_override: str | None = None
    prompt_overrides: dict = field(default_factory=dict)
    tool_permissions: list[str] = field(default_factory=list)
    execution_mode: ExecutionMode = ExecutionMode.BEST_EFFORT

    def __post_init__(self, **kwargs):
        """Ignore unknown fields for backwards compatibility (POD side)."""
        pass


@dataclass
class AgentResult:
    """Response from agent pod to router."""

    task_id: str
    content: str
    tool_history: list[dict] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    memory_writes: list[dict] = field(default_factory=list)
    error: str | None = None


class AgentPodProtocol(Protocol):
    """Protocol for agent pod implementations."""

    async def execute(self, task: AgentTask) -> AgentResult:
        """Execute a task and return result.

        Args:
            task: The task to execute.

        Returns:
            AgentResult with content, tokens, memory writes, or error.
        """
        ...

    async def health_check(self) -> bool:
        """Check if the agent pod is healthy.

        Returns:
            True if pod is ready to accept tasks, False otherwise.
        """
        ...

    async def update_config(self, config: dict) -> None:
        """Update user-specific configuration.

        Args:
            config: User configuration (soul prompt, tools, etc.)
        """
        ...
