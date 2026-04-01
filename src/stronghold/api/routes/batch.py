"""Batch API endpoints — async task submission with polling.

- POST   /v1/stronghold/batch/tasks — submit async task (auth)
- GET    /v1/stronghold/batch/tasks — list user's tasks (auth)
- GET    /v1/stronghold/batch/tasks/{task_id} — poll status (auth)
- DELETE /v1/stronghold/batch/tasks/{task_id} — cancel (auth)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.batch.manager import BatchTask

router = APIRouter(prefix="/v1/stronghold/batch/tasks")


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated mutations."""
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return  # Bearer token — not CSRF-vulnerable
    if not request.cookies:
        return  # No cookies = not a browser session
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


async def _authenticate(request: Request) -> tuple[Any, Any]:
    """Authenticate and return (auth, container). CSRF checked after auth."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    _check_csrf(request)
    return auth, container


@router.post("")
async def submit_batch_task(request: Request) -> JSONResponse:
    """Submit a batch task for async processing."""
    auth, container = await _authenticate(request)

    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    execution_mode: str = body.get("execution_mode", "best_effort")
    callback_url: str = body.get("callback_url", "")

    if not messages:
        raise HTTPException(status_code=400, detail="'messages' is required")

    task = BatchTask(
        user_id=auth.user_id,
        org_id=auth.org_id,
        messages=messages,
        execution_mode=execution_mode,
        callback_url=callback_url,
    )
    task = await container.batch_manager.submit(task)

    return JSONResponse(
        status_code=200,
        content={"task_id": task.id, "status": task.status},
    )


@router.get("")
async def list_batch_tasks(
    request: Request,
    limit: int = 20,
) -> JSONResponse:
    """List the caller's batch tasks."""
    auth, container = await _authenticate(request)
    limit = min(max(limit, 1), 100)

    tasks = await container.batch_manager.list_for_user(
        user_id=auth.user_id,
        org_id=auth.org_id,
        limit=limit,
    )

    return JSONResponse(
        content={
            "tasks": [
                {
                    "task_id": t.id,
                    "status": t.status,
                    "execution_mode": t.execution_mode,
                    "progress": t.progress,
                    "created_at": t.created_at,
                }
                for t in tasks
            ],
        },
    )


@router.get("/{task_id}")
async def get_batch_task(task_id: str, request: Request) -> JSONResponse:
    """Poll batch task status."""
    auth, container = await _authenticate(request)

    task = await container.batch_manager.get(task_id, org_id=auth.org_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return JSONResponse(
        content={
            "task_id": task.id,
            "status": task.status,
            "progress": task.progress,
            "result": task.result,
            "error": task.error,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
        },
    )


@router.delete("/{task_id}")
async def cancel_batch_task(task_id: str, request: Request) -> JSONResponse:
    """Cancel a batch task."""
    auth, container = await _authenticate(request)

    cancelled = await container.batch_manager.cancel(task_id, org_id=auth.org_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Task not found or not cancellable")

    return JSONResponse(content={"task_id": task_id, "status": "cancelled"})
