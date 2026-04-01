"""Tests for the background worker: connects to Container, polls task queue, routes requests."""

from __future__ import annotations

import asyncio
from typing import Any

from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.agents.worker import AgentWorker
from stronghold.types.auth import AuthContext


class _FakeContainer:
    """Minimal fake Container for worker tests.

    Provides a task_queue and a route_request that records calls.
    No mocks — just a simple class with the required interface.
    """

    def __init__(self, task_queue: InMemoryTaskQueue) -> None:
        self.task_queue = task_queue
        self.routed_requests: list[dict[str, Any]] = []
        self._route_error: Exception | None = None

    def set_route_error(self, error: Exception) -> None:
        """Configure route_request to raise an error."""
        self._route_error = error

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        """Fake route_request that records calls and returns canned responses."""
        self.routed_requests.append(
            {
                "messages": messages,
                "auth": auth,
                "session_id": session_id,
                "intent_hint": intent_hint,
            }
        )
        if self._route_error is not None:
            raise self._route_error

        content = "Worker processed: " + (messages[-1].get("content", "") if messages else "")
        return {
            "id": "stronghold-worker",
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


def _make_worker(
    *,
    route_error: Exception | None = None,
) -> tuple[AgentWorker, _FakeContainer, InMemoryTaskQueue]:
    """Create a worker with a fake container and shared task queue."""
    queue = InMemoryTaskQueue()
    container = _FakeContainer(task_queue=queue)
    if route_error is not None:
        container.set_route_error(route_error)
    worker = AgentWorker(container=container)
    return worker, container, queue


class TestWorkerStartsAndStops:
    """Worker lifecycle: starts polling, shuts down cleanly."""

    async def test_worker_starts_and_stops_on_idle(self) -> None:
        """Worker loop exits after idle timeout with no tasks."""
        worker, _, _ = _make_worker()
        # max_idle_seconds=0.2 → should exit quickly with no tasks
        await worker.run_loop(max_idle_seconds=0.2)
        # If we get here, the worker exited cleanly

    async def test_worker_shutdown_signal_stops_loop(self) -> None:
        """Worker respects shutdown signal and exits the loop."""
        worker, _, queue = _make_worker()
        worker.request_shutdown()
        # Even with a long idle timeout, shutdown signal should stop immediately
        await worker.run_loop(max_idle_seconds=60.0)


class TestWorkerProcessesTask:
    """Worker claims and processes tasks via container.route_request."""

    async def test_processes_single_task(self) -> None:
        """Worker claims a task, routes through container, marks completed."""
        worker, container, queue = _make_worker()

        task_id = await queue.submit(
            {
                "messages": [{"role": "user", "content": "hello world"}],
                "session_id": "sess-1",
            }
        )

        processed = await worker.process_one()
        assert processed is True

        # Verify route_request was called
        assert len(container.routed_requests) == 1
        req = container.routed_requests[0]
        assert req["messages"] == [{"role": "user", "content": "hello world"}]
        assert req["session_id"] == "sess-1"
        assert req["auth"] is not None  # Worker provides system auth

        # Verify task marked completed
        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "completed"
        assert "Worker processed: hello world" in task["result"]["content"]

    async def test_processes_task_with_auth_context(self) -> None:
        """Worker passes auth from task payload if provided."""
        worker, container, queue = _make_worker()

        await queue.submit(
            {
                "messages": [{"role": "user", "content": "test"}],
                "auth": {
                    "user_id": "user-42",
                    "username": "alice",
                    "org_id": "org-1",
                    "roles": ["admin"],
                },
            }
        )

        await worker.process_one()

        req = container.routed_requests[0]
        auth = req["auth"]
        assert isinstance(auth, AuthContext)
        assert auth.user_id == "user-42"
        assert auth.org_id == "org-1"

    async def test_processes_multiple_tasks_in_loop(self) -> None:
        """Worker processes all pending tasks then exits on idle."""
        worker, container, queue = _make_worker()

        await queue.submit({"messages": [{"role": "user", "content": "task 1"}]})
        await queue.submit({"messages": [{"role": "user", "content": "task 2"}]})
        await queue.submit({"messages": [{"role": "user", "content": "task 3"}]})

        await worker.run_loop(max_idle_seconds=0.3)

        assert len(container.routed_requests) == 3
        # All three tasks should be completed
        tasks = await queue.list_tasks(status="completed")
        assert len(tasks) == 3


class TestWorkerHandlesEmptyQueue:
    """Worker behavior when queue is empty."""

    async def test_returns_false_on_empty_queue(self) -> None:
        """process_one returns False when no tasks are pending."""
        worker, _, _ = _make_worker()
        processed = await worker.process_one()
        assert processed is False

    async def test_idle_loop_exits_after_timeout(self) -> None:
        """Worker loop exits after max_idle_seconds with empty queue."""
        worker, _, _ = _make_worker()
        import time

        start = time.monotonic()
        await worker.run_loop(max_idle_seconds=0.3)
        elapsed = time.monotonic() - start
        # Should have waited roughly 0.3s (with some tolerance)
        assert 0.2 < elapsed < 1.0


class TestWorkerHandlesErrors:
    """Worker error handling: task failures, exceptions."""

    async def test_task_failure_marks_task_failed(self) -> None:
        """When route_request raises, task is marked failed with error."""
        worker, _, queue = _make_worker(route_error=RuntimeError("LLM exploded"))

        task_id = await queue.submit({"messages": [{"role": "user", "content": "boom"}]})

        processed = await worker.process_one()
        assert processed is True

        task = await queue.get(task_id)
        assert task is not None
        assert task["status"] == "failed"
        assert "LLM exploded" in task["error"]

    async def test_failed_task_does_not_stop_loop(self) -> None:
        """A failed task does not crash the worker loop."""
        queue = InMemoryTaskQueue()
        container = _FakeContainer(task_queue=queue)

        # First task will fail
        container.set_route_error(RuntimeError("fail"))
        await queue.submit({"messages": [{"role": "user", "content": "fail task"}]})

        worker = AgentWorker(container=container)
        processed = await worker.process_one()
        assert processed is True

        # Clear the error — next task should succeed
        container._route_error = None
        await queue.submit({"messages": [{"role": "user", "content": "ok task"}]})

        processed = await worker.process_one()
        assert processed is True

        tasks = await queue.list_tasks()
        statuses = {t["id"]: t["status"] for t in tasks}
        assert "failed" in statuses.values()
        assert "completed" in statuses.values()


class TestWorkerSignalHandling:
    """Signal handling for graceful shutdown."""

    async def test_shutdown_flag_stops_processing(self) -> None:
        """request_shutdown sets the flag that stops the run loop."""
        worker, _, queue = _make_worker()

        # Submit tasks but request shutdown before loop starts
        for i in range(5):
            await queue.submit({"messages": [{"role": "user", "content": f"task {i}"}]})

        worker.request_shutdown()
        await worker.run_loop(max_idle_seconds=10.0)

        # Loop should exit immediately without processing tasks
        pending = await queue.list_tasks(status="pending")
        assert len(pending) == 5  # None processed

    async def test_shutdown_during_loop(self) -> None:
        """Shutdown during active processing stops after current task."""
        worker, container, queue = _make_worker()

        # Submit a task
        await queue.submit({"messages": [{"role": "user", "content": "last task"}]})

        # Schedule shutdown after a brief delay
        async def _delayed_shutdown() -> None:
            await asyncio.sleep(0.05)
            worker.request_shutdown()

        # Run loop and delayed shutdown concurrently
        await asyncio.gather(
            worker.run_loop(max_idle_seconds=10.0),
            _delayed_shutdown(),
        )

        # The first task may or may not have been processed
        # but the loop should have exited
