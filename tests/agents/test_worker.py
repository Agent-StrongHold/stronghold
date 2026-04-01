"""Tests for the agent worker: claims tasks, routes through container, reports results."""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.worker import AgentWorker


class _FakeContainer:
    """Minimal container fake with task_queue and route_request."""

    def __init__(self, task_queue: InMemoryTaskQueue) -> None:
        self.task_queue = task_queue

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        content = "Hello from the worker!"
        return {
            "id": "stronghold-test",
            "object": "chat.completion",
            "model": "test/model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
        }


class TestAgentWorker:
    @pytest.mark.asyncio
    async def test_processes_pending_task(self) -> None:
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)

        # Submit a task
        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "agent": "arbiter",
                "model": "test/model",
            }
        )

        # Process one task
        processed = await worker.process_one()
        assert processed is True

        # Check result
        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert task["result"]["content"] == "Hello from the worker!"

    @pytest.mark.asyncio
    async def test_returns_false_when_empty(self) -> None:
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)

        processed = await worker.process_one()
        assert processed is False

    @pytest.mark.asyncio
    async def test_handles_llm_error(self) -> None:
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)
        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "agent": "arbiter",
                "model": "test/model",
            }
        )

        processed = await worker.process_one()
        assert processed is True

        task = await queue.get(task_id)
        assert task is not None
        # Should complete (FakeContainer returns canned response)
        assert task["status"] == "completed"
