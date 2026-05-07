"""Tests for GraphPipelineExecutor (story 15.2)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from stronghold.orchestrator.executor import GraphPipelineExecutor
from stronghold.orchestrator.graph import PipelineGraph, PipelineNode
from stronghold.orchestrator.pipeline import PipelineRun

from datetime import UTC, datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _node(
    name: str,
    agent_name: str = "test-agent",
    depends_on: tuple[str, ...] = (),
    skip_if: Any = None,
    on_complete: Any = None,
    timeout_seconds: float = 600.0,
) -> PipelineNode:
    return PipelineNode(
        name=name,
        agent_name=agent_name,
        prompt_template="task: {" + name + "}" if depends_on else "task start",
        depends_on=depends_on,
        skip_if=skip_if,
        on_complete=on_complete,
        timeout_seconds=timeout_seconds,
    )


def _run(issue_number: int = 1) -> PipelineRun:
    return PipelineRun(
        id=f"test-{issue_number}",
        issue_number=issue_number,
        title="Test Issue",
        repo="org/repo",
        created_at=datetime.now(UTC),
    )


def _make_engine(outputs: dict[str, str], *, fail: set[str] | None = None) -> Any:
    """
    Build a minimal fake engine.

    outputs: work_id → output text for completed items
    fail: set of work_ids that should be reported as failed
    """
    fail = fail or set()
    work_items: dict[str, MagicMock] = {}

    def dispatch(*, work_id: str, agent_name: str, messages: list, **kwargs: Any) -> None:
        item = MagicMock()
        item.work_id = work_id
        if work_id in fail:
            item.status = MagicMock(value="failed")
            item.error = "agent error"
            item.result = None
        else:
            item.status = MagicMock(value="completed")
            item.error = ""
            # result formatted as litellm-style dict
            text = outputs.get(work_id, "")
            item.result = {
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}]
            }
        work_items[work_id] = item

    engine = MagicMock()
    engine.dispatch.side_effect = dispatch
    engine.get.side_effect = lambda wid: work_items.get(wid)
    engine.has_agent.return_value = True
    engine.cancel = MagicMock()
    return engine


# ── AC1: single node stores output ───────────────────────────────────────────

async def test_single_node_stores_output() -> None:
    engine = _make_engine({"test-1-plan": "my plan text"})
    graph = PipelineGraph([_node("plan")])
    run = _run()
    executor = GraphPipelineExecutor(engine)
    result = await executor.execute(graph, run, auth=None)
    assert result.context["plan"] == "my plan text"
    assert result.status == "completed"


# ── AC2: linear chain — B's prompt sees A's output ────────────────────────────

async def test_linear_chain_dep_output_in_prompt() -> None:
    dispatched_prompts: dict[str, str] = {}

    def dispatch(*, work_id: str, agent_name: str, messages: list, **kwargs: Any) -> None:
        dispatched_prompts[work_id] = messages[0]["content"]

    engine = _make_engine({"test-1-plan": "plan output", "test-1-code": "code output"})
    # Override dispatch to also record prompts
    original_dispatch = engine.dispatch.side_effect

    def tracking_dispatch(*, work_id: str, agent_name: str, messages: list, **kwargs: Any) -> None:
        dispatched_prompts[work_id] = messages[0]["content"]
        original_dispatch(work_id=work_id, agent_name=agent_name, messages=messages, **kwargs)

    engine.dispatch.side_effect = tracking_dispatch

    graph = PipelineGraph([
        _node("plan"),
        PipelineNode(
            name="code",
            agent_name="test-agent",
            prompt_template="implement using plan: {plan}",
            depends_on=("plan",),
        ),
    ])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    assert result.context["plan"] == "plan output"
    assert result.context["code"] == "code output"
    assert "plan output" in dispatched_prompts["test-1-code"]


# ── AC3: skip_if=True prevents dispatch ──────────────────────────────────────

async def test_skip_if_prevents_dispatch() -> None:
    engine = _make_engine({})
    graph = PipelineGraph([_node("decompose", skip_if=lambda ctx: True)])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    engine.dispatch.assert_not_called()
    assert "decompose" in result.skipped_stages


# ── AC4: skipped node satisfies downstream ────────────────────────────────────

async def test_skipped_node_satisfies_downstream() -> None:
    engine = _make_engine({"test-1-scaffold": "scaffolded"})
    graph = PipelineGraph([
        _node("decompose", skip_if=lambda ctx: True),
        _node("scaffold", depends_on=("decompose",)),
    ])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    assert result.context.get("scaffold") == "scaffolded"
    assert result.status == "completed"


# ── AC5: agent failure halts execution ───────────────────────────────────────

async def test_agent_failure_halts_execution() -> None:
    engine = _make_engine({}, fail={"test-1-plan"})
    graph = PipelineGraph([
        _node("plan"),
        _node("code", depends_on=("plan",)),
    ])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    assert "plan" in result.status
    # code must not have been dispatched
    dispatched_work_ids = [c.kwargs["work_id"] for c in engine.dispatch.call_args_list]
    assert not any("code" in wid for wid in dispatched_work_ids)


# ── AC6: missing agent is skipped, not failed ────────────────────────────────

async def test_missing_agent_skips_not_fails() -> None:
    engine = _make_engine({})
    engine.has_agent.return_value = False
    graph = PipelineGraph([_node("audit")])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    assert result.status != "failed at audit"
    assert "audit" in result.skipped_stages


# ── AC7: timeout halts and cancels ───────────────────────────────────────────

async def test_timeout_halts_and_cancels() -> None:
    # Engine never transitions to completed — item stays "running"
    work_item = MagicMock()
    work_item.status = MagicMock(value="running")
    work_item.result = None
    work_item.error = ""

    engine = MagicMock()
    engine.has_agent.return_value = True
    engine.dispatch.return_value = None
    engine.get.return_value = work_item
    engine.cancel = MagicMock()

    graph = PipelineGraph([_node("plan", timeout_seconds=0.05)])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    assert "plan" in result.status
    engine.cancel.assert_called()


# ── AC8: on_complete invoked on success ──────────────────────────────────────

async def test_on_complete_invoked_on_success() -> None:
    calls: list[tuple[Any, str]] = []

    async def hook(run: Any, output: str) -> None:
        calls.append((run, output))

    engine = _make_engine({"test-1-plan": "the plan"})
    graph = PipelineGraph([_node("plan", on_complete=hook)])
    run = _run()
    await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    assert len(calls) == 1
    assert calls[0][1] == "the plan"


# ── AC9: on_complete exception propagates ────────────────────────────────────

async def test_on_complete_exception_propagates() -> None:
    async def bad_hook(run: Any, output: str) -> None:
        raise RuntimeError("hook exploded")

    engine = _make_engine({"test-1-plan": "out"})
    graph = PipelineGraph([_node("plan", on_complete=bad_hook)])
    run = _run()
    with pytest.raises(RuntimeError, match="hook exploded"):
        await GraphPipelineExecutor(engine).execute(graph, run, auth=None)


# ── AC10: two independent entry nodes both dispatched ────────────────────────

async def test_two_independent_entry_nodes_both_dispatched() -> None:
    engine = _make_engine({"test-1-A": "a out", "test-1-B": "b out"})
    graph = PipelineGraph([_node("A"), _node("B")])
    run = _run()
    result = await GraphPipelineExecutor(engine).execute(graph, run, auth=None)
    dispatched = {c.kwargs["work_id"] for c in engine.dispatch.call_args_list}
    assert "test-1-A" in dispatched
    assert "test-1-B" in dispatched
    assert result.status == "completed"
