"""PipelineTrace — a null-safe Trace wrapper for pipeline code."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.tracing.noop import NoopTrace

if TYPE_CHECKING:
    from stronghold.protocols.tracing import Span, Trace


class PipelineTrace:
    """Wraps ``Trace | None`` so pipeline steps never branch on it.

    Accepts a real ``Trace`` or ``None``. When ``None``, delegates to a
    ``NoopTrace`` so every span/score/update/end call is safe to call
    unconditionally, eliminating the ``if trace: ... else: ...`` pattern
    that inflates cyclomatic complexity in ``Agent.handle`` and
    ``Conduit.route_request``.

    Satisfies the ``Trace`` protocol and can be used anywhere a ``Trace``
    is expected.
    """

    def __init__(self, trace: Trace | None) -> None:
        self._t: Trace = trace if trace is not None else NoopTrace()

    @property
    def trace_id(self) -> str:
        return self._t.trace_id

    def span(self, name: str) -> Span:
        return self._t.span(name)

    def score(self, name: str, value: float, comment: str = "") -> None:
        self._t.score(name, value, comment)

    def update(self, metadata: dict[str, Any]) -> None:
        self._t.update(metadata)

    def end(self) -> None:
        self._t.end()
