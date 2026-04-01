"""Agent Worker: claims tasks from the queue and routes them through the Container.

Runs in its own pod/process. Picks up tasks from the shared task queue,
routes them through container.route_request() (full Conduit pipeline),
and reports results back to the queue.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from stronghold.types.auth import SYSTEM_AUTH, AuthContext, IdentityKind

logger = logging.getLogger("stronghold.worker")


class AgentWorker:
    """Claims tasks from the queue and processes them via the Container pipeline.

    The worker uses container.task_queue to poll for pending tasks and
    container.route_request() to process them through the full Conduit
    pipeline (classify, route, agent.handle).
    """

    def __init__(self, container: Any) -> None:
        self._container = container
        self._queue = container.task_queue
        self._shutdown_requested = False

    def request_shutdown(self) -> None:
        """Signal the worker to stop after the current task completes."""
        self._shutdown_requested = True

    async def process_one(self) -> bool:
        """Claim and process one task. Returns True if a task was processed."""
        task = await self._queue.claim()
        if task is None:
            return False

        task_id: str = task["id"]
        payload: dict[str, Any] = task.get("payload", {})

        try:
            result = await self._route_task(payload)
            await self._queue.complete(task_id, result)
        except Exception as exc:
            logger.exception("Task %s failed", task_id)
            await self._queue.fail(task_id, str(exc))

        return True

    async def _route_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route a task through the Container's Conduit pipeline."""
        messages: list[dict[str, Any]] = payload.get("messages", [])
        session_id: str | None = payload.get("session_id")
        intent_hint: str = payload.get("intent_hint", "")

        # Build auth context from payload or fall back to SYSTEM_AUTH
        auth = self._build_auth(payload.get("auth"))

        response: dict[str, Any] = await self._container.route_request(
            messages,
            auth=auth,
            session_id=session_id,
            intent_hint=intent_hint,
        )

        # Extract content from the OpenAI-compatible response
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")

        return {
            "content": content,
            "model": response.get("model", "unknown"),
            "response": response,
        }

    @staticmethod
    def _build_auth(auth_data: dict[str, Any] | None) -> AuthContext:
        """Build an AuthContext from task payload data, or use SYSTEM_AUTH."""
        if auth_data is None:
            return SYSTEM_AUTH

        roles_raw = auth_data.get("roles", [])
        roles = frozenset(roles_raw) if isinstance(roles_raw, list) else frozenset()

        return AuthContext(
            user_id=auth_data.get("user_id", "system"),
            username=auth_data.get("username", ""),
            org_id=auth_data.get("org_id", ""),
            team_id=auth_data.get("team_id", ""),
            roles=roles,
            kind=IdentityKind(auth_data.get("kind", "system")),
            auth_method=auth_data.get("auth_method", "task_queue"),
        )

    async def run_loop(self, max_idle_seconds: float = 5.0) -> None:
        """Run the worker loop: claim -> process -> repeat.

        Exits when:
        - Shutdown is requested via request_shutdown()
        - No tasks are claimed for max_idle_seconds
        """
        idle_time = 0.0
        poll_interval = 0.1

        while not self._shutdown_requested and idle_time < max_idle_seconds:
            processed = await self.process_one()
            if processed:
                idle_time = 0.0
            else:
                await asyncio.sleep(poll_interval)
                idle_time += poll_interval
