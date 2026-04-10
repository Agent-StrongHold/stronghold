"""A2A peer endpoint — Stronghold as an A2A-compatible agent host.

ADR-K8S-028: implements the A2A task lifecycle:
  - agent_cards/list — discover available agents
  - agent_cards/get — get a specific Agent Card
  - tasks/create — submit a task to an agent
  - tasks/get — poll task status
  - tasks/cancel — cancel a running task
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.a2a")

router = APIRouter(prefix="/a2a")

# In-memory task store (postgres persistence in follow-up)
_tasks: dict[str, dict[str, Any]] = {}


async def _get_auth(request: Request) -> Any:
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers),
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


# ── Agent Cards ──────────────────────────────────────────────────────


@router.get("/agent_cards/list")
async def agent_cards_list(request: Request) -> JSONResponse:
    """List available Agent Cards (A2A discovery)."""
    auth = await _get_auth(request)
    container = request.app.state.container
    org_id = auth.org_id if hasattr(auth, "org_id") else ""

    cards = []
    for agent in container.agents.values():
        identity = agent.identity
        if org_id and identity.org_id and identity.org_id != org_id:
            continue
        cards.append({
            "id": identity.name,
            "name": identity.name,
            "description": identity.description,
            "version": identity.version,
            "capabilities": {
                "reasoning_strategy": identity.reasoning_strategy,
                "tools": list(identity.tools),
                "max_tool_rounds": identity.max_tool_rounds,
            },
            "trust_tier": identity.trust_tier,
            "active": identity.active,
        })

    return JSONResponse(content={"agent_cards": cards})


@router.get("/agent_cards/get/{agent_id}")
async def agent_cards_get(agent_id: str, request: Request) -> JSONResponse:
    """Get a specific Agent Card."""
    auth = await _get_auth(request)
    container = request.app.state.container

    agent = container.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    identity = agent.identity
    org_id = auth.org_id if hasattr(auth, "org_id") else ""
    if org_id and identity.org_id and identity.org_id != org_id:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return JSONResponse(content={
        "id": identity.name,
        "name": identity.name,
        "description": identity.description,
        "version": identity.version,
        "capabilities": {
            "reasoning_strategy": identity.reasoning_strategy,
            "tools": list(identity.tools),
            "skills": list(identity.skills),
            "max_tool_rounds": identity.max_tool_rounds,
            "delegation_mode": identity.delegation_mode,
            "sub_agents": list(identity.sub_agents),
        },
        "trust_tier": identity.trust_tier,
        "model": identity.model,
        "model_fallbacks": list(identity.model_fallbacks),
        "active": identity.active,
    })


# ── Task Lifecycle ───────────────────────────────────────────────────


@router.post("/tasks/create")
async def tasks_create(request: Request) -> JSONResponse:
    """Create a new A2A task for an agent."""
    auth = await _get_auth(request)
    body = await request.json()

    agent_id = body.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="Missing 'agent_id'")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="Missing 'messages'")

    container = request.app.state.container
    agent = container.agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    execution_mode = body.get("execution_mode", "best_effort")
    token_budget = body.get("token_budget")

    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    task = {
        "id": task_id,
        "agent_id": agent_id,
        "status": "submitted",
        "messages": messages,
        "execution_mode": execution_mode,
        "token_budget": token_budget,
        "result": None,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "created_by": auth.user_id if hasattr(auth, "user_id") else "",
        "org_id": auth.org_id if hasattr(auth, "org_id") else "",
    }
    _tasks[task_id] = task

    return JSONResponse(
        content={"task_id": task_id, "status": "submitted"},
        status_code=201,
    )


@router.get("/tasks/get/{task_id}")
async def tasks_get(task_id: str, request: Request) -> JSONResponse:
    """Get current state of an A2A task."""
    await _get_auth(request)

    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    return JSONResponse(content=task)


@router.post("/tasks/cancel/{task_id}")
async def tasks_cancel(task_id: str, request: Request) -> JSONResponse:
    """Cancel a running A2A task."""
    await _get_auth(request)

    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    if task["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Task already in terminal state: {task['status']}",
        )

    task["status"] = "cancelled"
    task["updated_at"] = datetime.now(timezone.utc).isoformat()

    return JSONResponse(content={"task_id": task_id, "status": "cancelled"})
