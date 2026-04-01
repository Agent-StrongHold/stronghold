"""Batch task manager — async submission, polling, callbacks."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class BatchTask:
    """A batch task submitted for async processing."""

    id: str = ""
    user_id: str = ""
    org_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    execution_mode: str = "best_effort"
    callback_url: str = ""
    status: str = "submitted"  # submitted, working, completed, failed, cancelled
    progress: str = ""
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0


class InMemoryBatchManager:
    """In-memory batch manager. PostgreSQL version for production."""

    def __init__(self) -> None:
        self._tasks: dict[str, BatchTask] = {}

    async def submit(self, task: BatchTask) -> BatchTask:
        """Submit a batch task. Assigns ID and timestamp if not set."""
        if not task.id:
            task.id = f"batch-{uuid4().hex[:12]}"
        task.created_at = time.time()
        task.status = "submitted"
        self._tasks[task.id] = task
        return task

    async def get(self, task_id: str, *, org_id: str) -> BatchTask | None:
        """Get a task by ID, scoped to org."""
        task = self._tasks.get(task_id)
        if task and task.org_id == org_id:
            return task
        return None

    async def list_for_user(
        self,
        *,
        user_id: str,
        org_id: str,
        limit: int = 20,
    ) -> list[BatchTask]:
        """List tasks for a user within their org."""
        tasks = [t for t in self._tasks.values() if t.user_id == user_id and t.org_id == org_id]
        # Sort by created_at descending (newest first)
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def update_status(
        self,
        task_id: str,
        *,
        status: str,
        progress: str = "",
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> bool:
        """Update the status of a task. Returns False if task not found."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status = status
        if progress:
            task.progress = progress
        if result is not None:
            task.result = result
        if error:
            task.error = error
        if status == "working" and task.started_at == 0.0:
            task.started_at = time.time()
        if status in ("completed", "failed", "cancelled"):
            task.completed_at = time.time()
        return True

    async def cancel(self, task_id: str, *, org_id: str) -> bool:
        """Cancel a task. Returns False if not found, wrong org, or terminal status."""
        task = self._tasks.get(task_id)
        if not task or task.org_id != org_id:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            return False
        task.status = "cancelled"
        task.completed_at = time.time()
        return True
