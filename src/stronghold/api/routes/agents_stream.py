"""Streaming structured request endpoint.

Sends SSE progress events as the agent works.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from stronghold.types.errors import QuotaExhaustedError

router = APIRouter(prefix="/v1/stronghold")


@router.post("/request/stream")
async def structured_request_stream(request: Request) -> StreamingResponse:
    """Handle a structured request with SSE progress updates."""
    container = request.app.state.container

    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    goal = body.get("goal", "")
    intent_hint = body.get("intent_hint", "") or body.get("intent", "")
    expected_output = body.get("expected_output", "")
    details = body.get("details", "")
    repo = body.get("repo", "")
    session_id: str | None = body.get("session_id")
    body.get("stream", False)

    if not goal:
        raise HTTPException(status_code=400, detail="'goal' is required")

    # Build prompt
    prompt_parts = [f"Goal: {goal}"]
    if expected_output:
        prompt_parts.append(f"Expected output: {expected_output}")
    if details:
        prompt_parts.append(f"Details: {details}")
    if repo:
        prompt_parts.append(f"GitHub repository: {repo}")
    user_content = "\n".join(prompt_parts)

    # Warden scan
    warden_verdict = await container.warden.scan(user_content, "user_input")
    if not warden_verdict.clean:

        async def blocked_stream() -> Any:
            yield _sse({"type": "error", "message": f"Blocked: {', '.join(warden_verdict.flags)}"})

        return StreamingResponse(blocked_stream(), media_type="text/event-stream")

    messages: list[dict[str, str]] = [{"role": "user", "content": user_content}]

    # Status queue for progress updates
    status_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def status_cb(msg: str) -> None:
        """Push status updates into the SSE queue."""
        await status_queue.put({"type": "status", "message": msg})

    async def run_agent() -> dict[str, Any]:
        """Run the agent pipeline, posting status updates to the queue."""
        await status_queue.put({"type": "status", "message": "Classifying intent..."})
        try:
            result = await container.route_request(
                messages,
                auth=auth_ctx,
                session_id=session_id,
                intent_hint=intent_hint,
                status_callback=status_cb,
            )
        except QuotaExhaustedError as e:
            await status_queue.put({"type": "error", "message": f"Quota exhausted: {e.detail}"})
            return {
                "choices": [
                    {
                        "message": {
                            "content": f"Request rejected: {e.detail}",
                        }
                    }
                ],
                "_routing": {"error": "quota_exhausted"},
            }
        # Flatten for SSE: JS expects content + _routing at top level
        content = ""
        if result.get("choices"):
            content = result["choices"][0].get("message", {}).get("content", "")
        await status_queue.put(
            {
                "type": "done",
                "content": content,
                "_routing": result.get("_routing", {}),
                "model": result.get("model", ""),
            }
        )
        final: dict[str, Any] = result
        return final

    async def stream_events() -> Any:
        """Yield SSE events: status updates then final result."""
        # Start the agent in background
        task = asyncio.create_task(run_agent())

        # Send initial status
        yield _sse({"type": "status", "message": "Starting..."})

        # Poll for updates
        while not task.done():
            try:
                update = await asyncio.wait_for(status_queue.get(), timeout=1.0)
                yield _sse(update)
                if update.get("type") == "done":
                    return
            except TimeoutError:
                yield _sse({"type": "heartbeat"})

        # Get the result if task completed without posting to queue
        try:
            result = task.result()
            content = ""
            if result.get("choices"):
                content = result["choices"][0].get("message", {}).get("content", "")
            yield _sse(
                {
                    "type": "done",
                    "content": content,
                    "_routing": result.get("_routing", {}),
                    "model": result.get("model", ""),
                }
            )
        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(stream_events(), media_type="text/event-stream")


@router.post("/chat/completions")
async def chat_completions(request: Request) -> StreamingResponse | dict[str, Any]:
    """Handle chat completions with streaming support."""
    container = request.app.state.container

    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    if not messages:
        raise HTTPException(status_code=400, detail="'messages' is required")

    # Warden scan the first user message
    warden_verdict = None
    if messages and messages[0].get("role") == "user":
        warden_verdict = await container.warden.scan(messages[0].get("content", ""), "user_input")
        if not warden_verdict.clean:
            if stream:

                async def blocked_stream() -> Any:
                    yield _sse(
                        {"type": "error", "message": f"Blocked: {', '.join(warden_verdict.flags)}"}
                    )

                return StreamingResponse(blocked_stream(), media_type="text/event-stream")
            else:
                raise HTTPException(
                    status_code=400, detail=f"Blocked: {', '.join(warden_verdict.flags)}"
                )

    if not stream:
        # Non-streaming path
        result = await container.route_chat(
            messages,
            auth=auth_ctx,
        )
        content = ""
        if result.get("choices"):
            content = result["choices"][0].get("message", {}).get("content", "")
        return {"choices": [{"message": {"content": content}}]}

    # Status queue for progress updates
    status_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    token_queue: asyncio.Queue[str] = asyncio.Queue()
    tool_call_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    tool_result_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def status_cb(msg: str) -> None:
        """Push status updates into the SSE queue."""
        await status_queue.put({"type": "status", "message": msg})

    async def token_cb(token: str) -> None:
        """Push token updates into the token queue."""
        await token_queue.put(token)

    async def tool_call_cb(tool_name: str, arguments: str, call_id: str) -> None:
        """Push tool call updates into the tool call queue."""
        await tool_call_queue.put(
            {
                "type": "tool_call",
                "tool_name": tool_name,
                "arguments": arguments,
                "call_id": call_id,
            }
        )

    async def tool_result_cb(tool_name: str, result: str, call_id: str) -> None:
        """Push tool result updates into the tool result queue."""
        await tool_result_queue.put(
            {"type": "tool_result", "tool_name": tool_name, "result": result, "call_id": call_id}
        )

    async def run_chat() -> dict[str, Any]:
        """Run the chat pipeline, posting status updates to the queue."""
        await status_queue.put({"type": "status", "message": "Processing..."})
        try:
            result = await container.route_chat(
                messages,
                auth=auth_ctx,
                status_callback=status_cb,
                token_callback=token_cb,
                tool_call_callback=tool_call_cb,
                tool_result_callback=tool_result_cb,
            )
        except QuotaExhaustedError as e:
            await status_queue.put({"type": "error", "message": f"Quota exhausted: {e.detail}"})
            return {
                "choices": [
                    {
                        "message": {
                            "content": f"Request rejected: {e.detail}",
                        }
                    }
                ],
                "_routing": {"error": "quota_exhausted"},
            }

        content = ""
        if result.get("choices"):
            content = result["choices"][0].get("message", {}).get("content", "")
        await status_queue.put(
            {
                "type": "done",
                "content": content,
                "_routing": result.get("_routing", {}),
                "model": result.get("model", ""),
            }
        )
        return result

    async def stream_events() -> Any:
        """Yield SSE events: status updates, tool calls/results, tokens, then final result."""
        task = asyncio.create_task(run_chat())

        yield _sse({"type": "status", "message": "Starting..."})

        # Track tool calls and results

        while not task.done():
            # Check status queue
            try:
                update = await asyncio.wait_for(status_queue.get(), timeout=0.1)
                # Add Warden audit to each event
                if warden_verdict:
                    update["warden_audit"] = {
                        "scanned_at": warden_verdict.scanned_at.isoformat()
                        if hasattr(warden_verdict, "scanned_at")
                        else None,
                        "scan_id": warden_verdict.scan_id
                        if hasattr(warden_verdict, "scan_id")
                        else None,
                        "scanned": warden_verdict.clean,
                    }
                yield _sse(update)
                if update.get("type") == "done":
                    return
            except TimeoutError:
                pass

            # Check tool call queue
            try:
                tool_call = await asyncio.wait_for(tool_call_queue.get(), timeout=0.0)
                tool_call_event = tool_call
                if warden_verdict:
                    tool_call_event["warden_audit"] = {
                        "scanned_at": warden_verdict.scanned_at.isoformat()
                        if hasattr(warden_verdict, "scanned_at")
                        else None,
                        "scan_id": warden_verdict.scan_id
                        if hasattr(warden_verdict, "scan_id")
                        else None,
                        "scanned": warden_verdict.clean,
                    }
                yield _sse(tool_call_event)
            except TimeoutError:
                pass

            # Check tool result queue
            try:
                tool_result = await asyncio.wait_for(tool_result_queue.get(), timeout=0.0)
                tool_result_event = tool_result
                if warden_verdict:
                    tool_result_event["warden_audit"] = {
                        "scanned_at": warden_verdict.scanned_at.isoformat()
                        if hasattr(warden_verdict, "scanned_at")
                        else None,
                        "scan_id": warden_verdict.scan_id
                        if hasattr(warden_verdict, "scan_id")
                        else None,
                        "scanned": warden_verdict.clean,
                    }
                yield _sse(tool_result_event)
            except TimeoutError:
                pass

            # Check token queue
            try:
                token = await asyncio.wait_for(token_queue.get(), timeout=0.0)
                token_event = {"type": "token", "token": token}
                if warden_verdict:
                    token_event["warden_audit"] = {
                        "scanned_at": warden_verdict.scanned_at.isoformat()
                        if hasattr(warden_verdict, "scanned_at")
                        else None,
                        "scan_id": warden_verdict.scan_id
                        if hasattr(warden_verdict, "scan_id")
                        else None,
                        "scanned": warden_verdict.clean,
                    }
                yield _sse(token_event)
            except TimeoutError:
                pass

        try:
            result = task.result()
            content = ""
            if result.get("choices"):
                content = result["choices"][0].get("message", {}).get("content", "")
            final_event = {
                "type": "done",
                "content": content,
                "_routing": result.get("_routing", {}),
                "model": result.get("model", ""),
            }
            # Add Warden audit to final event
            if warden_verdict:
                final_event["warden_audit"] = {
                    "scanned_at": warden_verdict.scanned_at.isoformat()
                    if hasattr(warden_verdict, "scanned_at")
                    else None,
                    "scan_id": warden_verdict.scan_id
                    if hasattr(warden_verdict, "scan_id")
                    else None,
                    "scanned": warden_verdict.clean,
                }
            yield _sse(final_event)
        except Exception as e:
            error_event = {"type": "error", "message": str(e)}
            # Add Warden audit to error event
            if warden_verdict:
                error_event["warden_audit"] = {
                    "scanned_at": warden_verdict.scanned_at.isoformat()
                    if hasattr(warden_verdict, "scanned_at")
                    else None,
                    "scan_id": warden_verdict.scan_id
                    if hasattr(warden_verdict, "scan_id")
                    else None,
                    "scanned": warden_verdict.clean,
                }
            yield _sse(error_event)

    return StreamingResponse(stream_events(), media_type="text/event-stream")


def _sse(data: dict[str, Any]) -> str:
    """Format a dict as an SSE event."""
    return f"data: {json.dumps(data)}\n\n"
