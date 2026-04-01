"""Extended tests for agent worker: failure handling, run_loop idle timeout."""

from __future__ import annotations

from typing import Any

from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.worker import AgentWorker


class _FakeContainer:
    """Minimal container fake with task_queue and route_request."""

    def __init__(
        self,
        task_queue: InMemoryTaskQueue,
        *,
        error: Exception | None = None,
    ) -> None:
        self.task_queue = task_queue
        self._error = error

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return {
            "id": "stronghold-test",
            "object": "chat.completion",
            "model": "test/model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "looped response"},
                    "finish_reason": "stop",
                }
            ],
        }


class TestWorkerProcessOneNoTasks:
    async def test_no_tasks_returns_false(self) -> None:
        """process_one with empty queue returns False."""
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)

        result = await worker.process_one()
        assert result is False


class TestWorkerProcessOneSuccess:
    async def test_task_available_processes_and_completes(self) -> None:
        """process_one claims a task, routes through container, and marks it completed."""
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)

        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "do something"}],
                "agent": "arbiter",
                "model": "test/model",
            }
        )

        processed = await worker.process_one()
        assert processed is True

        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert task["result"]["content"] == "looped response"


class TestWorkerProcessOneFailure:
    async def test_route_failure_marks_task_as_failed(self) -> None:
        """When route_request raises, the task is marked as failed with the error."""
        queue = InMemoryTaskQueue()
        container = _FakeContainer(
            task_queue=queue,
            error=RuntimeError("connection refused"),
        )
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
        assert task["status"] == "failed"
        assert "connection refused" in task["error"]


class TestWorkerRunLoop:
    async def test_run_loop_processes_tasks_then_idles_out(self) -> None:
        """run_loop processes all available tasks then exits after idle timeout."""
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)

        # Submit 3 tasks
        ids = []
        for i in range(3):
            task_id = await queue.submit(
                {
                    "messages": [{"role": "user", "content": f"task {i}"}],
                    "agent": "arbiter",
                    "model": "test/model",
                }
            )
            ids.append(task_id)

        # Run with short idle timeout so it exits quickly after tasks are done
        await worker.run_loop(max_idle_seconds=0.5)

        # All 3 tasks should be completed
        for task_id in ids:
            task = await queue.get(task_id)
            assert task is not None
            assert task["status"] == "completed"

    async def test_run_loop_exits_on_idle_with_no_tasks(self) -> None:
        """run_loop exits quickly when there are no tasks at all."""
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)
        worker = AgentWorker(container=container)

        # Should return without error after idle timeout
        await worker.run_loop(max_idle_seconds=0.3)
