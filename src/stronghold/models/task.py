"""Task model for persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from stronghold.memory.outcomes import InMemoryOutcomeStore

if TYPE_CHECKING:
    from datetime import datetime


@dataclass
class Task:
    """Represents a task with its state and metadata."""

    task_id: str
    status: str
    progress: int
    result: dict | None
    usage: dict
    callback_url: str
    created_at: datetime
    updated_at: datetime


class TaskStore(InMemoryOutcomeStore[Task]):
    """In-memory store for tasks."""

    def __init__(self) -> None:
        super().__init__()
        self._store: dict[str, Task] = {}

    def create(self, task: Task) -> None:
        """Create a new task."""
        self._store[task.task_id] = task

    def get(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._store.get(task_id)

    def update(self, task: Task) -> None:
        """Update an existing task."""
        self._store[task.task_id] = task

    def delete(self, task_id: str) -> None:
        """Delete a task."""
        self._store.pop(task_id, None)


from fastapi import APIRouter, Depends, HTTPException, status

from stronghold.security.auth_static import StaticKeyAuthProvider

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext

router = APIRouter(prefix="/v1", tags=["tasks"])


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def create_task(
    task: Task,
    auth: AuthContext = Depends(StaticKeyAuthProvider()),
) -> Task:
    """Create a new task."""
    container = auth.container
    container.tasks.create(task)
    return task


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    auth: AuthContext = Depends(StaticKeyAuthProvider()),
) -> Task:
    """Get a task by ID."""
    container = auth.container
    task = container.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
