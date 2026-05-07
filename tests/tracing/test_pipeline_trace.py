"""Tests for PipelineTrace — the null-safe Trace wrapper."""

from stronghold.protocols.tracing import Trace
from stronghold.tracing.pipeline import PipelineTrace
from tests.fakes import NoopTrace, RecordingTrace


def test_wraps_none_with_noop_no_errors() -> None:
    t = PipelineTrace(None)
    with t.span("step.one") as s:
        s.set_input({"x": 1})
        s.set_output({"y": 2})
    t.score("quality", 0.9)
    t.update({"model": "test"})
    t.end()


def test_trace_id_when_none() -> None:
    t = PipelineTrace(None)
    assert isinstance(t.trace_id, str)
    assert t.trace_id != ""


def test_delegates_span_to_real_trace() -> None:
    rec = RecordingTrace()
    t = PipelineTrace(rec)
    t.span("conduit.classify")
    assert "conduit.classify" in rec.spans


def test_delegates_score_to_real_trace() -> None:
    rec = RecordingTrace()
    t = PipelineTrace(rec)
    t.score("blocked", 1.0, "warden flagged")
    assert rec.scores == [("blocked", 1.0, "warden flagged")]


def test_delegates_update_to_real_trace() -> None:
    rec = RecordingTrace()
    t = PipelineTrace(rec)
    t.update({"task_type": "code"})
    assert rec.updates == [{"task_type": "code"}]


def test_delegates_end_to_real_trace() -> None:
    rec = RecordingTrace()
    t = PipelineTrace(rec)
    t.end()
    assert rec.ended


def test_trace_id_delegates_to_real_trace() -> None:
    rec = RecordingTrace()
    t = PipelineTrace(rec)
    assert t.trace_id == "recording-trace-id"


def test_satisfies_trace_protocol() -> None:
    assert isinstance(PipelineTrace(None), Trace)
    assert isinstance(PipelineTrace(RecordingTrace()), Trace)


def test_noop_trace_passthrough() -> None:
    noop = NoopTrace()
    t = PipelineTrace(noop)
    assert t.trace_id == "noop-trace-id"
    t.end()


def test_span_context_manager_works() -> None:
    rec = RecordingTrace()
    t = PipelineTrace(rec)
    with t.span("agent.warden") as s:
        s.set_input({"text_length": 42})
        s.set_output({"clean": True})
    assert "agent.warden" in rec.spans
