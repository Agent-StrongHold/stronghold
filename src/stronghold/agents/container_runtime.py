"""A2A container runtime for custom agent strategies.

Provides dataclasses for container-based agent execution and an in-memory
ContainerRuntime that simulates dispatch. Real K8s Job dispatch is a
follow-up implementation — this module defines the interface and provides
the in-memory version for testing and local development.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from typing import Any

from stronghold.types.errors import StrongholdError


class ContainerNotAvailableError(StrongholdError):
    """Raised when the container runtime is unavailable."""

    code = "CONTAINER_NOT_AVAILABLE"


@dataclass(frozen=True)
class ContainerStrategy:
    """Defines how to run an agent in a container.

    Attributes:
        image: Container image (e.g. ``stronghold/ranger:latest``).
        command: Entrypoint command list.
        timeout: Maximum execution time in seconds.
        resource_limits: K8s-style resource limits (cpu, memory).
    """

    image: str
    command: list[str]
    timeout: int = 300
    resource_limits: dict[str, str] = field(
        default_factory=lambda: {"cpu": "500m", "memory": "512Mi"}
    )


@dataclass(frozen=True)
class A2ATask:
    """An agent-to-agent task for container dispatch.

    Attributes:
        task_id: Unique identifier for this task.
        agent_name: Target agent to execute.
        messages: Chat messages to pass to the agent.
        callback_url: URL for completion callback.
        token_budget: Maximum tokens the agent may consume.
    """

    task_id: str
    agent_name: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    callback_url: str = ""
    token_budget: int = 0


class ContainerRuntime:
    """In-memory container runtime for A2A task dispatch.

    Simulates container execution for testing and local development.
    A production implementation would dispatch K8s Jobs.

    Args:
        available: Whether the runtime accepts dispatches. Set to ``False``
            to simulate a runtime outage.
    """

    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        self._containers: dict[str, dict[str, Any]] = {}

    async def dispatch(self, task: A2ATask, strategy: ContainerStrategy) -> dict[str, Any]:
        """Simulate dispatching a task to a container.

        Args:
            task: The A2A task to execute.
            strategy: Container configuration for execution.

        Returns:
            A dict with task_id, status, container_id, callback_token,
            and the strategy parameters used.

        Raises:
            ContainerNotAvailableError: If the runtime is unavailable.
        """
        if not self._available:
            raise ContainerNotAvailableError("Container runtime is not available")

        container_id = f"ctr-{uuid.uuid4().hex[:12]}"
        callback_token = self._generate_callback_token(task.agent_name, task.task_id)

        self._containers[container_id] = {
            "task_id": task.task_id,
            "agent_name": task.agent_name,
            "status": "running",
            "strategy": strategy,
        }

        return {
            "task_id": task.task_id,
            "agent_name": task.agent_name,
            "status": "completed",
            "container_id": container_id,
            "callback_token": callback_token,
            "timeout": strategy.timeout,
            "resource_limits": dict(strategy.resource_limits),
            "image": strategy.image,
            "command": list(strategy.command),
            "token_budget": task.token_budget,
        }

    async def health_check(self, container_id: str) -> bool:
        """Check whether a container is known and healthy.

        Args:
            container_id: The container identifier returned by :meth:`dispatch`.

        Returns:
            ``True`` if the container exists, ``False`` otherwise.
        """
        return container_id in self._containers

    @staticmethod
    def _generate_callback_token(agent_name: str, task_id: str) -> str:
        """Generate a short-lived token for callback authentication.

        Combines agent name, task ID, and a random nonce to produce a
        unique, unpredictable token. A production implementation would
        issue a signed JWT with expiration.

        Args:
            agent_name: The agent this token authorises callbacks for.
            task_id: The task this token is scoped to.

        Returns:
            A hex-encoded callback token.
        """
        nonce = secrets.token_hex(16)
        raw = f"{agent_name}:{task_id}:{nonce}"
        return hashlib.sha256(raw.encode()).hexdigest()
