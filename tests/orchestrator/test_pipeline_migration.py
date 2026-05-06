"""Tests for BUILDER_PIPELINE migration to graph nodes (story 15.3)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stronghold.orchestrator.graph import PipelineNode
from stronghold.orchestrator.pipeline import (
    BUILDER_PIPELINE,
    BuilderPipeline,
    PipelineRun,
    _decompose_on_complete,
    _scaffold_on_complete,
)

from datetime import UTC, datetime


def _run(issue_number: int = 1) -> PipelineRun:
    return PipelineRun(
        id=f"test-{issue_number}",
        issue_number=issue_number,
        title="Test Issue",
        repo="org/repo",
        created_at=datetime.now(UTC),
    )


def _mock_engine() -> Any:
    work_item = MagicMock()
    work_item.status = MagicMock(value="completed")
    work_item.error = ""
    work_item.result = {"choices": [{"message": {"content": "stage output"}}]}

    engine = MagicMock()
    engine.has_agent.return_value = True
    engine.dispatch.return_value = None
    engine.get.return_value = work_item
    engine.cancel = MagicMock()
    return engine


# ── AC2: decompose skip_if is a callable ─────────────────────────────────────

def test_decompose_skip_if_is_callable() -> None:
    """decompose.skip_if must be a callable predicate, not a string."""
    decompose = next(n for n in BUILDER_PIPELINE if n.name == "decompose")
    assert callable(decompose.skip_if), "decompose.skip_if must be a callable"

    # skip_decompose=True in context → returns True
    assert decompose.skip_if({"skip_decompose": True}) is True
    # skip_decompose absent or False → returns False
    assert decompose.skip_if({}) is False
    assert decompose.skip_if({"skip_decompose": False}) is False


# ── AC3: review skip_if checks implement (code) output ───────────────────────

def test_review_skip_if_checks_context_content() -> None:
    """review.skip_if must be a callable checking the implement stage output."""
    review = next(n for n in BUILDER_PIPELINE if n.name == "review")
    assert callable(review.skip_if), "review.skip_if must be a callable"

    # implement output contains clean signal → skip review
    assert review.skip_if({"implement": "LGTM, no violations found"}) is True
    assert review.skip_if({"implement": "all checks pass"}) is True

    # implement output has violations → do NOT skip
    assert review.skip_if({"implement": "Found 3 violations in module X"}) is False
    assert review.skip_if({}) is False


# ── AC4: decompose on_complete emits spec ────────────────────────────────────

async def test_decompose_on_complete_emits_spec() -> None:
    """_decompose_on_complete emits and persists a spec via spec_store."""
    decompose = next(n for n in BUILDER_PIPELINE if n.name == "decompose")
    assert decompose.on_complete is not None, "decompose must have an on_complete hook"

    spec_store = AsyncMock()
    fake_spec = MagicMock()
    fake_spec.to_dict.return_value = {"issue_number": 42}

    run = _run(42)
    run.title = "My Issue"
    run.context["_spec_store"] = spec_store
    # no "_spec" key yet → hook should emit

    with patch(
        "stronghold.orchestrator.pipeline._emit_and_save_spec", return_value=fake_spec
    ) as mock_emit:
        await decompose.on_complete(run, "<spec yaml>")

    mock_emit.assert_called_once_with(42, "My Issue", "<spec yaml>", spec_store)
    spec_store.save.assert_awaited_once_with(fake_spec)
    assert run.context["spec"] == {"issue_number": 42}


# ── AC5: scaffold on_complete enriches spec ──────────────────────────────────

async def test_scaffold_on_complete_enriches_spec() -> None:
    """_scaffold_on_complete enriches the spec with property tests."""
    scaffold = next(n for n in BUILDER_PIPELINE if n.name == "scaffold")
    assert scaffold.on_complete is not None, "scaffold must have an on_complete hook"

    spec_store = AsyncMock()
    original_spec = MagicMock()
    enriched_spec = MagicMock()
    enriched_spec.to_dict.return_value = {"enriched": True}

    run = _run()
    run.context["_spec_store"] = spec_store
    run.context["_spec"] = original_spec

    with patch(
        "stronghold.orchestrator.pipeline._enrich_spec_with_property_tests",
        return_value=enriched_spec,
    ) as mock_enrich:
        await scaffold.on_complete(run, "scaffold output")

    mock_enrich.assert_called_once_with(original_spec)
    spec_store.save.assert_awaited_once_with(enriched_spec)
    assert run.context["spec"] == {"enriched": True}
    assert run.context["_spec"] is enriched_spec


# ── AC6: no radon block worse than C after migration ─────────────────────────

def test_pipeline_py_no_block_worse_than_c() -> None:
    """pipeline.py must have no cyclomatic-complexity block at rank D or worse."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable, "-m", "radon", "cc", "-s", "-n", "D",
            "src/stronghold/orchestrator/pipeline.py",
        ],
        capture_output=True,
        text=True,
        cwd="/home/user/stronghold",
    )
    assert result.stdout.strip() == "", (
        f"pipeline.py has complexity blocks rated D or worse:\n{result.stdout}"
    )


# ── AC1 (regression): execute() delegates to GraphPipelineExecutor ────────────

async def test_execute_delegates_to_graph_executor() -> None:
    """BuilderPipeline.execute must go through GraphPipelineExecutor."""
    from stronghold.orchestrator.executor import GraphPipelineExecutor

    engine = _mock_engine()
    pipeline = BuilderPipeline(engine)
    expected_run = _run()

    with patch.object(
        GraphPipelineExecutor,
        "execute",
        new_callable=AsyncMock,
        return_value=expected_run,
    ) as mock_exec:
        result = await pipeline.execute(issue_number=1, title="test", repo="org/repo")

    mock_exec.assert_awaited_once()
    # First arg to execute is a PipelineGraph
    graph_arg = mock_exec.call_args.args[0]
    from stronghold.orchestrator.graph import PipelineGraph
    assert isinstance(graph_arg, PipelineGraph)
    assert len(graph_arg) == 5
