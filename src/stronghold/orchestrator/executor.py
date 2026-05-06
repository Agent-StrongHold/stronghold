"""Graph-aware pipeline executor."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from stronghold.agents.messages import LLMResponse

if TYPE_CHECKING:
    from stronghold.orchestrator.graph import PipelineGraph, PipelineNode

logger = logging.getLogger("stronghold.orchestrator.executor")

_POLL_START = 1.0
_POLL_MAX = 10.0
_POLL_FACTOR = 1.5

_DONE_STATUSES = frozenset({"completed", "failed", "cancelled"})


class GraphPipelineExecutor:
    """Drive a PipelineGraph to completion.

    Traversal: find ready nodes → check skip → dispatch → poll → store output
    → call on_complete → repeat until no ready nodes remain.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def execute(
        self,
        graph: PipelineGraph,
        run: Any,
        *,
        auth: Any,
    ) -> Any:
        """Drive the graph to completion. Returns run with updated status/context."""
        errors = graph.validate()
        if errors:
            run.status = f"invalid graph: {'; '.join(errors)}"
            return run

        run.status = "running"
        completed: frozenset[str] = frozenset()
        skipped: frozenset[str] = frozenset()

        while True:
            ready = graph.ready(completed, skipped)
            if not ready:
                break

            halted = False
            for node in ready:
                outcome = await self._run_node(node, run, auth)
                if outcome == "completed":
                    completed = completed | {node.name}
                elif outcome == "skipped":
                    skipped = skipped | {node.name}
                    run.skipped_stages.append(node.name)
                else:
                    halted = True
                    break

            if halted:
                return run

        if run.status == "running":
            run.status = "completed"
        return run

    async def _run_node(self, node: PipelineNode, run: Any, auth: Any) -> str:
        """Returns "completed", "skipped", or "failed"."""
        if node.skip_if is not None and node.skip_if(run.context):
            logger.info("Executor: skipping %s (skip_if)", node.name)
            return "skipped"

        if not self._engine.has_agent(node.agent_name):
            logger.warning(
                "Executor: skipping %s (agent %r not loaded)", node.name, node.agent_name
            )
            return "skipped"

        prompt = _build_prompt(node.prompt_template, run.context)
        work_id = f"{run.id}-{node.name}"

        self._engine.dispatch(
            work_id=work_id,
            agent_name=node.agent_name,
            messages=[{"role": "user", "content": prompt}],
            trigger="pipeline",
            priority_tier="P5",
            intent_hint="code_gen",
            metadata={
                "issue_number": run.issue_number,
                "pipeline_run": run.id,
                "stage": node.name,
            },
        )

        item = await self._poll(work_id, node.timeout_seconds)

        if item is None:
            run.status = f"failed at {node.name}"
            run.failed_stage_error = "Work item lost"
            logger.error("Executor: %s FAILED: work item lost", node.name)
            return "failed"

        if item == "timeout":
            self._engine.cancel(work_id)
            run.status = f"failed at {node.name}"
            run.failed_stage_error = f"Stage timed out after {node.timeout_seconds:.0f}s"
            logger.error("Executor: %s TIMED OUT", node.name)
            return "failed"

        if item.status.value == "failed":
            run.status = f"failed at {node.name}"
            run.failed_stage_error = item.error
            logger.error("Executor: %s FAILED: %s", node.name, item.error)
            return "failed"

        output = _extract_output(item)
        run.context[node.name] = output

        if node.on_complete is not None:
            await node.on_complete(run, output)

        if run.status.startswith("failed at "):
            return "failed"

        logger.info("Executor: %s completed", node.name)
        return "completed"

    async def _poll(self, work_id: str, timeout: float) -> Any:
        """Poll until terminal status. Returns item, None (lost), or "timeout"."""
        poll_interval = _POLL_START
        elapsed = 0.0
        while elapsed < timeout:
            item = self._engine.get(work_id)
            if item and item.status.value in _DONE_STATUSES:
                return item
            sleep_for = min(poll_interval, max(timeout - elapsed, 0.001))
            await asyncio.sleep(sleep_for)
            elapsed += sleep_for
            poll_interval = min(poll_interval * _POLL_FACTOR, _POLL_MAX)

        item = self._engine.get(work_id)
        if item and item.status.value in _DONE_STATUSES:
            return item
        if item is None:
            return None
        return "timeout"


def _build_prompt(template: str, context: dict[str, Any]) -> str:
    class _Default(dict):  # type: ignore[type-arg]
        def __missing__(self, key: str) -> str:
            return ""

    try:
        return template.format_map(_Default(context))
    except (ValueError, KeyError):
        return template


def _extract_output(item: Any) -> str:
    if not item.result:
        return ""
    resp = LLMResponse(item.result)
    return resp.content or str(item.result.get("content", ""))
