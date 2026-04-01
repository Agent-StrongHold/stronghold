"""Structured SSE events for agent execution progress."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SSEEvent:
    """A single Server-Sent Event."""

    event: str  # "status", "tool_call", "tool_result", "token", "done", "error"
    data: dict[str, Any] = field(default_factory=dict)

    def format(self) -> str:
        """Format as SSE wire protocol."""
        return f"event: {self.event}\ndata: {json.dumps(self.data)}\n\n"


class EventCollector:
    """Collects SSE events during request processing.

    Used as status_callback in conduit.route_request().
    Consumers iterate via the events property.
    """

    def __init__(self) -> None:
        self._events: list[SSEEvent] = []
        self._closed = False

    async def emit(self, event: str, **data: Any) -> None:
        """Emit an SSE event."""
        self._events.append(SSEEvent(event=event, data=data))

    async def emit_status(self, phase: str, detail: str = "") -> None:
        """Convenience: emit a status event."""
        await self.emit("status", phase=phase, detail=detail, timestamp=time.time())

    async def emit_tool_call(self, tool: str, arguments: dict[str, Any] | None = None) -> None:
        """Emit a tool_call event."""
        await self.emit("tool_call", tool=tool, arguments=arguments or {})

    async def emit_tool_result(self, tool: str, success: bool, detail: str = "") -> None:
        """Emit a tool_result event."""
        await self.emit("tool_result", tool=tool, success=success, detail=detail)

    async def emit_done(self, usage: dict[str, Any] | None = None) -> None:
        """Emit a done event and close the collector."""
        await self.emit("done", usage=usage or {})
        self._closed = True

    def close(self) -> None:
        """Close the collector without emitting an event."""
        self._closed = True

    @property
    def events(self) -> list[SSEEvent]:
        """Return a copy of the event list."""
        return list(self._events)

    @property
    def is_closed(self) -> bool:
        """Whether the collector has been closed."""
        return self._closed

    def format_all(self) -> str:
        """Format all events as SSE stream."""
        return "".join(e.format() for e in self._events)
