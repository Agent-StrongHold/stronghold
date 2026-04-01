"""Comprehensive tests for tracing backends: Phoenix and Noop.

Covers trace/span creation, nesting, metadata, scoring, end lifecycle,
context-manager semantics, error propagation, chaining, and noop passthrough.
"""

from __future__ import annotations

from stronghold.protocols.tracing import Span, Trace, TracingBackend
from stronghold.tracing.noop import NoopSpan, NoopTrace, NoopTracingBackend
from stronghold.tracing.phoenix_backend import PhoenixSpan, PhoenixTrace, PhoenixTracingBackend

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_phoenix_backend() -> PhoenixTracingBackend:
    """Create a PhoenixTracingBackend pointed at a dummy endpoint."""
    return PhoenixTracingBackend(endpoint="http://localhost:6006")


# ===========================================================================
# Noop backend — verify full passthrough without side effects
# ===========================================================================


class TestNoopTracingBackendProtocol:
    """NoopTracingBackend satisfies the TracingBackend protocol."""

    def test_noop_backend_is_tracing_backend(self) -> None:
        backend = NoopTracingBackend()
        assert isinstance(backend, TracingBackend)

    def test_noop_trace_is_trace(self) -> None:
        trace = NoopTrace()
        assert isinstance(trace, Trace)

    def test_noop_span_is_span(self) -> None:
        span = NoopSpan()
        assert isinstance(span, Span)


class TestNoopTraceCreation:
    """NoopTracingBackend.create_trace returns a well-formed NoopTrace."""

    def test_create_trace_returns_noop_trace(self) -> None:
        backend = NoopTracingBackend()
        trace = backend.create_trace()
        assert isinstance(trace, NoopTrace)

    def test_trace_id_is_constant(self) -> None:
        backend = NoopTracingBackend()
        t1 = backend.create_trace()
        t2 = backend.create_trace(user_id="u", session_id="s", name="n")
        assert t1.trace_id == "noop-trace"
        assert t2.trace_id == "noop-trace"

    def test_create_trace_ignores_all_kwargs(self) -> None:
        backend = NoopTracingBackend()
        trace = backend.create_trace(
            user_id="user-1",
            session_id="sess-1",
            name="my-trace",
            metadata={"agent": "artificer", "org": "acme"},
        )
        assert trace.trace_id == "noop-trace"


class TestNoopSpanPassthrough:
    """NoopSpan methods are no-ops that return self for chaining."""

    def test_span_context_manager(self) -> None:
        trace = NoopTrace()
        with trace.span("test") as span:
            assert isinstance(span, NoopSpan)

    def test_set_input_returns_self(self) -> None:
        span = NoopSpan()
        result = span.set_input({"query": "hello"})
        assert result is span

    def test_set_output_returns_self(self) -> None:
        span = NoopSpan()
        result = span.set_output({"response": "world"})
        assert result is span

    def test_set_usage_returns_self(self) -> None:
        span = NoopSpan()
        result = span.set_usage(input_tokens=100, output_tokens=50, model="gpt-4")
        assert result is span

    def test_chained_calls(self) -> None:
        span = NoopSpan()
        result = (
            span.set_input("data")
            .set_output("result")
            .set_usage(input_tokens=1, output_tokens=2, model="m")
        )
        assert result is span

    def test_exit_completes_without_error(self) -> None:
        span = NoopSpan()
        span.__exit__(None, None, None)

    def test_exit_with_exception_completes_without_error(self) -> None:
        span = NoopSpan()
        exc = ValueError("boom")
        span.__exit__(ValueError, exc, None)


class TestNoopTraceLifecycle:
    """NoopTrace score/update/end are no-ops that don't raise."""

    def test_score_does_not_raise(self) -> None:
        trace = NoopTrace()
        trace.score("quality", 0.9, comment="good")
        trace.score("latency", 0.5)

    def test_update_does_not_raise(self) -> None:
        trace = NoopTrace()
        trace.update({"model": "gpt-4", "agent": "artificer"})
        trace.update({})

    def test_end_does_not_raise(self) -> None:
        trace = NoopTrace()
        trace.end()

    def test_full_lifecycle_noop(self) -> None:
        """Complete request lifecycle through noop: no errors, no side effects."""
        backend = NoopTracingBackend()
        trace = backend.create_trace(
            user_id="u1",
            session_id="s1",
            name="request",
            metadata={"agent": "ranger"},
        )

        with trace.span("classify") as cs:
            cs.set_input({"text": "search something"})
            cs.set_output({"task_type": "search"})

        with trace.span("route") as rs:
            rs.set_input({"task_type": "search"}).set_output({"model": "gpt-3.5"})

        with trace.span("agent.handle") as ags:
            ags.set_usage(input_tokens=50, output_tokens=25, model="gpt-3.5")

        trace.score("quality", 0.8, comment="ok")
        trace.update({"model_used": "gpt-3.5"})
        trace.end()


# ===========================================================================
# Phoenix backend — real OTEL spans (no external connectivity needed)
# ===========================================================================


class TestPhoenixBackendProtocol:
    """PhoenixTracingBackend satisfies the TracingBackend protocol."""

    def test_phoenix_backend_is_tracing_backend(self) -> None:
        backend = _make_phoenix_backend()
        assert isinstance(backend, TracingBackend)

    def test_phoenix_trace_is_trace(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        assert isinstance(trace, Trace)
        trace.end()

    def test_phoenix_span_is_span(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("child") as span:
            assert isinstance(span, Span)
        trace.end()


class TestPhoenixTraceCreation:
    """PhoenixTracingBackend.create_trace returns a well-formed PhoenixTrace."""

    def test_create_trace_returns_phoenix_trace(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        assert isinstance(trace, PhoenixTrace)
        trace.end()

    def test_trace_id_is_nonempty_string(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        assert isinstance(trace.trace_id, str)
        assert len(trace.trace_id) > 0
        trace.end()

    def test_trace_id_is_not_noop(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        assert trace.trace_id != "noop-trace"
        assert trace.trace_id != "noop-trace-id"
        trace.end()

    def test_each_trace_gets_unique_id(self) -> None:
        backend = _make_phoenix_backend()
        t1 = backend.create_trace(name="a")
        t2 = backend.create_trace(name="b")
        assert t1.trace_id != t2.trace_id
        t1.end()
        t2.end()

    def test_create_trace_with_metadata(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(
            user_id="user-1",
            session_id="sess-1",
            name="test-trace",
            metadata={"agent": "artificer", "task_type": "code"},
        )
        assert trace.trace_id
        trace.end()

    def test_create_trace_with_empty_args(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace()
        assert trace.trace_id
        trace.end()

    def test_create_trace_default_name(self) -> None:
        """When name is empty, PhoenixTrace should still be created."""
        backend = _make_phoenix_backend()
        trace = backend.create_trace(user_id="u", session_id="s")
        assert isinstance(trace, PhoenixTrace)
        trace.end()


class TestPhoenixSpanCreation:
    """PhoenixTrace.span() creates PhoenixSpan instances."""

    def test_span_returns_phoenix_span(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        span = trace.span("child")
        assert isinstance(span, PhoenixSpan)
        span.__exit__(None, None, None)
        trace.end()

    def test_span_context_manager(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("child") as span:
            assert span is not None
            assert isinstance(span, PhoenixSpan)
        trace.end()

    def test_multiple_sequential_spans(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")

        with trace.span("classify"):
            pass
        with trace.span("route"):
            pass
        with trace.span("handle"):
            pass

        trace.end()


class TestPhoenixSpanAttributes:
    """PhoenixSpan attribute setters return self for chaining."""

    def test_set_input_returns_self(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("s") as span:
            result = span.set_input({"query": "hello"})
            assert result is span
        trace.end()

    def test_set_output_returns_self(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("s") as span:
            result = span.set_output({"response": "world"})
            assert result is span
        trace.end()

    def test_set_usage_returns_self(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("llm-call") as span:
            result = span.set_usage(input_tokens=100, output_tokens=50, model="gpt-4")
            assert result is span
        trace.end()

    def test_set_usage_without_model(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("llm-call") as span:
            result = span.set_usage(input_tokens=10, output_tokens=5)
            assert result is span
        trace.end()

    def test_chained_attribute_calls(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("s") as span:
            result = (
                span.set_input({"q": "hello"})
                .set_output({"r": "world"})
                .set_usage(input_tokens=10, output_tokens=5, model="m")
            )
            assert result is span
        trace.end()

    def test_large_input_truncation(self) -> None:
        """Input > 1000 chars should not raise — phoenix truncates internally."""
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        with trace.span("s") as span:
            huge_input = "x" * 5000
            result = span.set_input(huge_input)
            assert result is span
        trace.end()


class TestPhoenixTraceScoring:
    """PhoenixTrace.score() records scores on the root span."""

    def test_single_score(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        trace.score("quality", 0.95, comment="good response")
        trace.end()

    def test_multiple_scores(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        trace.score("quality", 0.9)
        trace.score("latency", 0.7, comment="a bit slow")
        trace.score("safety", 1.0, comment="clean")
        trace.end()

    def test_score_stored_internally(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        assert isinstance(trace, PhoenixTrace)
        trace.score("quality", 0.9, comment="good")
        trace.score("safety", 1.0)
        # PhoenixTrace stores scores in _scores list
        assert len(trace._scores) == 2  # noqa: SLF001
        assert trace._scores[0] == ("quality", 0.9, "good")  # noqa: SLF001
        assert trace._scores[1] == ("safety", 1.0, "")  # noqa: SLF001
        trace.end()


class TestPhoenixTraceMetadata:
    """PhoenixTrace.update() sets metadata attributes on root span."""

    def test_update_metadata(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        trace.update({"model": "gpt-4", "agent": "artificer", "task_type": "code"})
        trace.end()

    def test_update_empty_metadata(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        trace.update({})
        trace.end()


class TestPhoenixTraceLifecycle:
    """Full trace lifecycle exercises."""

    def test_end_completes(self) -> None:
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")
        trace.end()

    def test_flush_does_not_raise(self) -> None:
        backend = _make_phoenix_backend()
        backend.flush()

    def test_span_error_propagation(self) -> None:
        """When an exception occurs inside a span, it records error attributes."""
        backend = _make_phoenix_backend()
        trace = backend.create_trace(name="test")

        try:
            with trace.span("failing"):
                msg = "deliberate error"
                raise RuntimeError(msg)
        except RuntimeError:
            pass  # Expected

        trace.end()

    def test_full_request_lifecycle(self) -> None:
        """Simulate a real request: classify -> route -> handle -> score -> end."""
        backend = _make_phoenix_backend()
        trace = backend.create_trace(
            user_id="user-1",
            session_id="sess-1",
            name="route_request",
            metadata={"org_id": "acme"},
        )

        with trace.span("conduit.classify") as cs:
            cs.set_input({"text": "write a function to sort a list"})
            cs.set_output({"task_type": "code", "classified_by": "keywords"})

        with trace.span("conduit.route") as rs:
            rs.set_input({"task_type": "code", "min_tier": "medium"})
            rs.set_output({"model": "test/large", "score": 0.85})

        with trace.span("agent.artificer") as ags:
            ags.set_input({"message_count": 3})
            ags.set_output({"response_length": 500})
            ags.set_usage(input_tokens=200, output_tokens=100, model="test/large")

        with trace.span("warden.scan_output") as ws:
            ws.set_input({"response_length": 500})
            ws.set_output({"verdict": "clean"})

        trace.update({"model": "test/large", "agent": "artificer"})
        trace.score("quality", 0.9, comment="clean code")
        trace.score("safety", 1.0)
        trace.end()


# ===========================================================================
# Cross-cutting: both backends behave equivalently through the protocol
# ===========================================================================


class TestProtocolParity:
    """Both backends can be used interchangeably through the protocol."""

    def _exercise_backend(self, backend: TracingBackend) -> None:
        """Run a standard trace lifecycle through any TracingBackend."""
        trace: Trace = backend.create_trace(
            user_id="u1",
            session_id="s1",
            name="parity-test",
            metadata={"key": "value"},
        )

        assert isinstance(trace.trace_id, str)
        assert len(trace.trace_id) > 0

        with trace.span("step-1") as s1:
            result: Span = s1.set_input("in").set_output("out")
            assert result is s1

        with trace.span("step-2") as s2:
            s2.set_usage(input_tokens=10, output_tokens=5, model="test")

        trace.score("accuracy", 0.95)
        trace.update({"done": "true"})
        trace.end()

    def test_noop_through_protocol(self) -> None:
        self._exercise_backend(NoopTracingBackend())

    def test_phoenix_through_protocol(self) -> None:
        self._exercise_backend(_make_phoenix_backend())
