"""Builder pipeline — chained agent execution for issue-to-merge flow.

The pipeline defines ordered stages that an issue flows through.
Each stage is an agent with a specific role. Stage ordering, skipping,
and post-completion hooks are declared on PipelineNode; GraphPipelineExecutor
drives execution.

Default pipeline:
  1. quartermaster  — decompose epic into atomic issues (skip if already atomic)
  2. archie          — scaffold protocols, fakes, file structure
  3. mason          — TDD: write tests, then implementation
  4. auditor        — review PR, post violation comments (skip if code is clean)
  5. gatekeeper     — final lint/format/merge-readiness check (skip if review clean)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from stronghold.orchestrator.graph import PipelineGraph, PipelineNode

logger = logging.getLogger("stronghold.orchestrator.pipeline")

_SPEC_SUMMARY_LIMIT = 2000
_CLEAN_SIGNALS = ("no violations", "lgtm", "approved", "all checks pass", "clean")


def build_spec_summary(spec: Any) -> str:
    """Build a text summary of a Spec for injection into pipeline prompts."""
    parts: list[str] = [f"Spec: {spec.title}"]

    if spec.protocols_touched:
        parts.append(f"Protocols: {', '.join(spec.protocols_touched)}")

    if spec.invariants:
        inv_lines = [f"  - {inv.name}: {inv.description}" for inv in spec.invariants]
        parts.append("Invariants:\n" + "\n".join(inv_lines))

    if spec.acceptance_criteria:
        crit_lines = [f"  - {c}" for c in spec.acceptance_criteria]
        parts.append("Acceptance criteria:\n" + "\n".join(crit_lines))

    summary = "\n".join(parts)
    if len(summary) > _SPEC_SUMMARY_LIMIT:
        summary = summary[: _SPEC_SUMMARY_LIMIT - 3] + "..."
    return summary


def _emit_and_save_spec(issue_number: int, title: str, body: str, store: Any) -> Any:
    """Create a Spec from issue metadata via the spec emitter."""
    from stronghold.builders.spec_emitter import emit_spec

    return emit_spec(issue_number=issue_number, title=title, body=body)


def _enrich_spec_with_property_tests(spec: Any) -> Any:
    """Generate property tests for a Spec's invariants and return updated Spec."""
    from stronghold.builders.property_gen import generate_property_tests
    from stronghold.types.spec import Spec

    tests = generate_property_tests(spec)
    return Spec(
        issue_number=spec.issue_number,
        title=spec.title,
        protocols_touched=spec.protocols_touched,
        invariants=spec.invariants,
        acceptance_criteria=spec.acceptance_criteria,
        files_touched=spec.files_touched,
        property_tests=tuple(tests),
        complexity=spec.complexity,
        status=spec.status,
        created_at=spec.created_at,
    )


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStage:
    """A single stage in the builder pipeline (kept for backward compatibility)."""

    name: str
    agent_name: str
    prompt_template: str
    status: StageStatus = StageStatus.PENDING
    result: dict[str, Any] | None = None
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    skip_if: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PipelineRun:
    """A complete pipeline execution for one issue."""

    id: str
    issue_number: int
    title: str
    repo: str
    stages: list[PipelineStage] = field(default_factory=list)
    current_stage: int = 0
    status: str = "pending"
    context: dict[str, Any] = field(default_factory=dict)
    skipped_stages: list[str] = field(default_factory=list)
    failed_stage_error: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "issue_number": self.issue_number,
            "title": self.title,
            "repo": self.repo,
            "status": self.status,
            "current_stage": self.current_stage,
            "stages": [s.to_dict() for s in self.stages],
            "created_at": self.created_at.isoformat(),
        }


# ── skip_if predicates ───────────────────────────────────────────────────────


def _decompose_skip_if(ctx: dict[str, Any]) -> bool:
    return bool(ctx.get("skip_decompose", False))


def _review_skip_if(ctx: dict[str, Any]) -> bool:
    implement_out = ctx.get("implement", "").lower()
    return any(sig in implement_out for sig in _CLEAN_SIGNALS)


def _cleanup_skip_if(ctx: dict[str, Any]) -> bool:
    review_out = ctx.get("review", "").lower()
    return any(sig in review_out for sig in _CLEAN_SIGNALS)


# ── on_complete hooks ────────────────────────────────────────────────────────


async def _decompose_on_complete(run: PipelineRun, output: str) -> None:
    """Emit and persist spec from decompose output."""
    spec_store = run.context.get("_spec_store")
    if spec_store is None:
        return
    if run.context.get("_spec") is not None:
        return
    spec = _emit_and_save_spec(run.issue_number, run.title, output, spec_store)
    await spec_store.save(spec)
    run.context["_spec"] = spec
    run.context["spec"] = spec.to_dict()
    run.context["verifications"] = []
    run.context["spec_summary"] = build_spec_summary(spec)


async def _scaffold_on_complete(run: PipelineRun, output: str) -> None:
    """Enrich spec with property tests after scaffold."""
    spec_store = run.context.get("_spec_store")
    spec = run.context.get("_spec")
    if spec_store is None or spec is None:
        return
    enriched = _enrich_spec_with_property_tests(spec)
    await spec_store.save(enriched)
    run.context["_spec"] = enriched
    run.context["spec"] = enriched.to_dict()
    run.context["spec_summary"] = build_spec_summary(enriched)


# ── Default pipeline nodes ───────────────────────────────────────────────────

BUILDER_PIPELINE: list[PipelineNode] = [
    PipelineNode(
        name="decompose",
        agent_name="quartermaster",
        skip_if=_decompose_skip_if,
        on_complete=_decompose_on_complete,
        prompt_template=(
            "Decompose this epic into atomic, implementable sub-issues. "
            "Each sub-issue must have:\n"
            "- A clear title\n"
            "- Acceptance criteria (testable)\n"
            "- File paths that will be touched\n"
            "- Estimated complexity (S/M/L)\n\n"
            "Epic: {title}\n"
            "Issue: https://github.com/{repo}/issues/{issue_number}\n\n"
            "Output a numbered list of sub-issues with details."
        ),
    ),
    PipelineNode(
        name="scaffold",
        agent_name="archie",
        depends_on=("decompose",),
        on_complete=_scaffold_on_complete,
        prompt_template=(
            "Read issue #{issue_number}: {title}\n\n"
            "{spec_summary}\n\n"
            "Create the scaffolding for this implementation:\n"
            "1. Define any new protocols in src/stronghold/protocols/\n"
            "2. Add fake implementations to tests/fakes.py\n"
            "3. Create empty module files with docstrings\n"
            "4. Update ARCHITECTURE.md if adding new components\n"
            "5. Generate property test stubs from spec invariants\n\n"
            "Previous stage output:\n{decompose}\n\n"
            "DO NOT write implementation code. Only structure."
        ),
    ),
    PipelineNode(
        name="implement",
        agent_name="mason",
        depends_on=("scaffold",),
        prompt_template=(
            "Implement issue #{issue_number}: {title}\n\n"
            "Repository: https://github.com/{repo}\n\n"
            "{spec_summary}\n\n"
            "Follow your TDD pipeline:\n"
            "1. Write failing tests based on acceptance criteria and spec invariants\n"
            "2. Implement minimum code to pass tests\n"
            "3. Verify all spec invariants hold via property tests\n"
            "4. Run quality gates: pytest, ruff, mypy, bandit\n"
            "5. Create a PR when all gates pass\n\n"
            "Scaffold from previous stage:\n{scaffold}\n\n"
            "Create a focused PR with your changes."
        ),
    ),
    PipelineNode(
        name="review",
        agent_name="auditor",
        depends_on=("implement",),
        skip_if=_review_skip_if,
        prompt_template=(
            "Review the PR created for issue #{issue_number}: {title}\n\n"
            "{spec_summary}\n\n"
            "Check for:\n"
            "- Spec invariant coverage (all invariants must have property tests)\n"
            "- Test coverage and quality\n"
            "- Security issues (injection, XSS, SSRF)\n"
            "- Multi-tenant isolation (org_id on all queries)\n"
            "- Protocol compliance (DI, no direct imports)\n"
            "- Code quality (naming, complexity, duplication)\n\n"
            "Previous stage output:\n{implement}\n\n"
            "Post your review as PR comments with ViolationCategory tags."
        ),
    ),
    PipelineNode(
        name="cleanup",
        agent_name="gatekeeper",
        depends_on=("review",),
        skip_if=_cleanup_skip_if,
        prompt_template=(
            "Final cleanup for issue #{issue_number}: {title}\n\n"
            "The auditor found these issues:\n{review}\n\n"
            "Fix all violations:\n"
            "1. Run ruff check --fix && ruff format\n"
            "2. Fix any mypy --strict errors\n"
            "3. Ensure all tests pass\n"
            "4. Push fixes to the existing PR branch\n\n"
            "Do NOT create a new PR. Push to the existing branch."
        ),
    ),
]


class BuilderPipeline:
    """Executes the full issue-to-merge pipeline via GraphPipelineExecutor.

    Usage:
        pipeline = BuilderPipeline(orchestrator_engine)
        run = await pipeline.execute(
            issue_number=42, title="Add caching", repo="Agent-StrongHold/stronghold",
        )

    With spec-driven verification:
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)
    """

    def __init__(
        self,
        engine: Any,
        *,
        spec_store: Any | None = None,
        spec_verifier: Any | None = None,
    ) -> None:
        self._engine = engine
        self._spec_store = spec_store
        self._spec_verifier = spec_verifier
        self._runs: dict[str, PipelineRun] = {}

    async def execute(
        self,
        *,
        issue_number: int,
        title: str,
        repo: str = "Agent-StrongHold/stronghold",
        skip_decompose: bool = True,
    ) -> PipelineRun:
        """Run the full pipeline for an issue."""
        from stronghold.orchestrator.executor import GraphPipelineExecutor

        run_id = f"pipeline-{issue_number}"
        stages = [
            PipelineStage(
                name=node.name,
                agent_name=node.agent_name,
                prompt_template=node.prompt_template,
            )
            for node in BUILDER_PIPELINE
        ]
        run = PipelineRun(
            id=run_id,
            issue_number=issue_number,
            title=title,
            repo=repo,
            stages=stages,
        )
        self._runs[run_id] = run

        # Populate context with pipeline parameters accessible to hooks and templates
        run.context.update(
            {
                "skip_decompose": skip_decompose,
                "issue_number": issue_number,
                "title": title,
                "repo": repo,
                "_spec_store": self._spec_store,
                "_spec_verifier": self._spec_verifier,
            }
        )

        # Load spec if store is available
        spec = None
        if self._spec_store is not None:
            spec = await self._spec_store.get(issue_number)
            if spec is not None:
                run.context["_spec"] = spec
                run.context["spec"] = spec.to_dict()
                run.context["verifications"] = []

        # Emit spec immediately when decompose will be skipped (atomic issue)
        if self._spec_store is not None and spec is None and skip_decompose:
            spec = _emit_and_save_spec(issue_number, title, "", self._spec_store)
            await self._spec_store.save(spec)
            run.context["_spec"] = spec
            run.context["spec"] = spec.to_dict()
            run.context["verifications"] = []

        run.context["spec_summary"] = build_spec_summary(spec) if spec is not None else ""

        # Wrap each node's on_complete with spec verification if configured
        nodes = self._wrap_nodes_with_verification(BUILDER_PIPELINE)
        graph = PipelineGraph(nodes)
        executor = GraphPipelineExecutor(self._engine)

        await executor.execute(graph, run, auth=None)

        self._reconcile_stages(run)
        return run

    def _wrap_nodes_with_verification(self, nodes: list[PipelineNode]) -> list[PipelineNode]:
        """Return nodes whose on_complete also runs spec verification."""
        if self._spec_verifier is None:
            return list(nodes)

        result = []
        for node in nodes:
            original = node.on_complete

            async def _hook(
                run: PipelineRun,
                output: str,
                _orig: Any = original,
                _name: str = node.name,
            ) -> None:
                if _orig is not None:
                    await _orig(run, output)
                spec = run.context.get("_spec")
                verifier = run.context.get("_spec_verifier")
                if spec is None or verifier is None:
                    return
                verification = await verifier.verify(spec, _name, {})
                run.context.setdefault("verifications", []).append(verification.to_dict())
                if not verification.passed:
                    run.status = f"failed at {_name}"
                    run.failed_stage_error = (
                        f"Spec verification failed: {', '.join(verification.failures)}"
                    )

            result.append(replace(node, on_complete=_hook))
        return result

    def _reconcile_stages(self, run: PipelineRun) -> None:
        """Update PipelineStage statuses from executor results (backward compat)."""
        failed_name = ""
        if run.status.startswith("failed at "):
            failed_name = run.status[len("failed at ") :]

        for stage in run.stages:
            if stage.name == failed_name:
                stage.status = StageStatus.FAILED
                stage.error = run.failed_stage_error
            elif stage.name in run.context and stage.name not in (
                "spec_summary",
                "_spec_store",
                "_spec_verifier",
                "_spec",
            ):
                stage.status = StageStatus.COMPLETED
            elif stage.name in run.skipped_stages:
                stage.status = StageStatus.SKIPPED
            # else: PENDING (default)

    def get_run(self, run_id: str) -> PipelineRun | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, object]]:
        return [r.to_dict() for r in self._runs.values()]
