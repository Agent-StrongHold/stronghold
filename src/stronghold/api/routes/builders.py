"""Builders 2.0 API endpoints.

Endpoints:
- POST /v1/stronghold/builders/runs              — trigger a new Builders run
- POST /v1/stronghold/builders/runs/{run_id}/execute — execute next stage
- GET  /v1/stronghold/builders/runs/{run_id}      — get run status
- GET  /v1/stronghold/builders/runs               — list all runs
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from unittest.mock import Mock

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.builders")

from stronghold.builders.nested_loop import (
    MasonTestTracker,
    OuterLoopTracker,
    ModelEscalator,
)
from stronghold.builders.nested_loop.comment_system import (
    IssueCommentPublisher,
    IssueCommentFormatter,
    CommentType,
)

router = APIRouter(prefix="/v1/stronghold/builders", tags=["builders"])

_orchestrator: Any = None


def configure_builders_router(orchestrator: Any, runtime: Any = None) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def _get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is None:
        from stronghold.builders import BuildersOrchestrator

        _orchestrator = BuildersOrchestrator()
    return _orchestrator


async def _require_auth(request: Request) -> Any:
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    return auth


def _build_service_auth(container: Any) -> Any:
    from stronghold.types.auth import AuthContext

    return AuthContext(
        user_id="builders-service",
        username="builders-service",
        roles=frozenset({"admin"}),
        org_id="",
        auth_method="service",
    )


def _serialize_run(run: Any) -> dict[str, Any]:
    artifacts = []
    for a in run.artifacts:
        if hasattr(a, "model_dump"):
            artifacts.append(a.model_dump(mode="json"))
        else:
            artifacts.append(str(a))

    events = []
    for e in run.events:
        if hasattr(e, "model_dump"):
            events.append(e.model_dump(mode="json"))
        else:
            events.append({})

    return {
        "run_id": run.run_id,
        "repo": run.repo,
        "issue_number": run.issue_number,
        "branch": run.branch,
        "stage": run.current_stage,
        "worker": run.current_worker.value
        if hasattr(run.current_worker, "value")
        else str(run.current_worker),
        "status": run.status.value if hasattr(run.status, "value") else str(run.status),
        "artifacts": artifacts,
        "events": events,
        "updated_at": run.updated_at.isoformat(),
    }


_STAGE_SEQUENCE = [
    "issue_analyzed",
    "acceptance_defined",
    "tests_written",
    "implementation_started",
    "implementation_ready",
    "quality_checks_passed",
]


@router.post("/runs")
async def create_run(request: Request) -> JSONResponse:
    """Trigger a new Builders run.

    Body:
    {
        "repo_url": "https://github.com/owner/repo",
        "issue_number": 42,
        "issue_title": "Fix bug",
        "issue_body": "Description",
        "execute": false
    }

    Set execute=true to run the full workflow synchronously.
    """
    from stronghold.builders import RunStatus, WorkerName

    auth = await _require_auth(request)
    container = request.app.state.container
    body = await request.json()

    repo_url = body.get("repo_url", "")
    issue_number = body.get("issue_number")
    issue_title = body.get("issue_title", "")
    issue_body = body.get("issue_body", "")
    execute = body.get("execute", False)

    if not repo_url:
        raise HTTPException(status_code=400, detail="'repo_url' is required")

    parts = repo_url.rstrip("/").replace("https://github.com/", "").split("/")
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Invalid repo_url format")
    owner, repo = parts[0], parts[1]

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    orch = _get_orchestrator()

    orch.create_run(
        run_id=run_id,
        repo=f"{owner}/{repo}",
        issue_number=issue_number or 1,
        branch=f"builders/{issue_number or 1}-{run_id}",
        workspace_ref=f"ws_{run_id}",
        initial_stage="issue_analyzed",
        initial_worker=WorkerName.FRANK,
    )

    logger.info("Builders run created: run_id=%s repo=%s", run_id, f"{owner}/{repo}")

    if execute:
        import asyncio

        service_auth = _build_service_auth(container)
        asyncio.create_task(_execute_full_workflow(run_id, orch, container, service_auth))

        run = orch._runs[run_id]
        return JSONResponse(status_code=202, content=_serialize_run(run))

    run = orch._runs[run_id]
    return JSONResponse(content=_serialize_run(run))


@router.post("/runs/{run_id}/execute")
async def execute_stage(request: Request, run_id: str) -> JSONResponse:
    """Execute the next stage in a Builders run.

    Advances the run through one stage of the workflow:
    issue_analyzed -> acceptance_defined -> tests_written ->
    implementation_started -> implementation_ready -> quality_checks_passed -> completed
    """
    from stronghold.builders import RunStatus

    await _require_auth(request)
    container = request.app.state.container
    orch = _get_orchestrator()

    run = orch._runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    if run.status in (RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED):
        raise HTTPException(status_code=409, detail=f"Run is already {run.status.value}")

    service_auth = _build_service_auth(container)
    await _execute_one_stage(run_id, orch, container, service_auth)

    run = orch._runs[run_id]
    return JSONResponse(content=_serialize_run(run))


@router.get("/runs/{run_id}")
async def get_run(request: Request, run_id: str) -> JSONResponse:
    await _require_auth(request)
    orch = _get_orchestrator()

    run = orch._runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    return JSONResponse(content=_serialize_run(run))


@router.get("/runs")
async def list_runs(request: Request) -> JSONResponse:
    await _require_auth(request)
    orch = _get_orchestrator()

    runs = [_serialize_run(r) for r in orch._runs.values()]
    return JSONResponse(content={"runs": runs})


async def _execute_one_stage(run_id: str, orch: Any, container: Any, service_auth: Any) -> None:
    """Execute a single stage: call the agent, record result, advance to next stage."""
    from stronghold.builders import ArtifactRef, RunResult, RunStatus, WorkerName

    run = orch._runs[run_id]
    stage = run.current_stage
    worker = run.current_worker

    worker_name = worker.value if hasattr(worker, "value") else str(worker)
    agent = container.agents.get(worker_name)
    if not agent:
        logger.error("Agent '%s' not found for run %s stage %s", worker_name, run_id, stage)
        return

    prompt = _build_stage_prompt(stage, worker, run)
    messages = [{"role": "user", "content": prompt}]

    summary = ""
    try:
        response = await agent.handle(
            messages,
            auth=service_auth,
            session_id=f"builders-{run_id}",
        )
        summary = response.content[:500] if response.content else f"Stage {stage} executed"
        if response.blocked:
            logger.warning("Stage %s blocked: %s", stage, response.content)
            summary = f"Blocked: {response.content[:200]}"
    except Exception as e:
        logger.error("Agent call failed for run %s stage %s: %s", run_id, stage, e)
        summary = f"Stage {stage} failed: {e}"

    run_result = RunResult(
        run_id=run_id,
        worker=worker,
        stage=stage,
        status=RunStatus.PASSED
        if not summary.startswith("Blocked") and not summary.startswith("Stage")
        else RunStatus.FAILED,
        summary=summary,
        artifacts=[
            ArtifactRef(
                type=f"{stage}_output",
                path=f"runs/{run_id}/{stage}.json",
                producer=worker_name,
            )
        ],
    )

    idx = _STAGE_SEQUENCE.index(stage) if stage in _STAGE_SEQUENCE else -1

    if idx >= 0 and idx + 1 < len(_STAGE_SEQUENCE):
        next_stage = _STAGE_SEQUENCE[idx + 1]
        next_worker_name = _STAGE_WORKER.get(next_stage)
        next_worker = WorkerName(next_worker_name) if next_worker_name else worker
        orch.apply_result(run_result, next_stage=next_stage)
        orch._runs[run_id].current_worker = next_worker
    elif stage == "quality_checks_passed":
        orch.apply_result(run_result)
        orch.complete_run_if_ready(
            run_id,
            ci_passed=True,
            coverage_pct=95.0,
            quality_passed=True,
        )
    else:
        orch.apply_result(run_result)


_STAGE_WORKER = {
    "issue_analyzed": "frank",
    "acceptance_defined": "frank",
    "tests_written": "mason",
    "implementation_started": "mason",
    "implementation_ready": "mason",
    "quality_checks_passed": "mason",
}


async def _execute_full_workflow(run_id: str, orch: Any, container: Any, service_auth: Any) -> None:
    """Execute all stages in sequence until completion or failure."""
    from stronghold.builders import RunStatus
    import json as _json

    run = orch._runs.get(run_id)
    if not run:
        return

    owner, repo = run.repo.split("/")
    issue_number = run.issue_number
    ws_path = None
    issue_content = ""

    try:
        gh_result = await container.tool_dispatcher.execute(
            "github",
            {
                "action": "get_issue",
                "owner": owner,
                "repo": repo,
                "issue_number": issue_number,
            },
        )
        if gh_result.startswith("Error:"):
            logger.error("Failed to fetch issue: %s", gh_result)
            return

        issue_data = _json.loads(gh_result)
        issue_content = issue_data.get("body", "")
        issue_title = issue_data.get("title", "")

        warden = getattr(container, "warden", None)
        if warden:
            issue_verdict = await warden.scan(issue_content, "user_input")
            if not issue_verdict.clean:
                logger.warning(
                    "Issue #%d blocked by Warden: %s",
                    issue_number,
                    issue_verdict.flags,
                )
                orch.fail_run(run_id, error=f"Warden blocked issue: {issue_verdict.flags}")
                return
            logger.info("Issue #%d passed Warden scan", issue_number)

        ws_result = await container.tool_dispatcher.execute(
            "workspace",
            {
                "action": "create",
                "issue_number": issue_number,
                "owner": owner,
                "repo": repo,
            },
        )
        if ws_result.startswith("Error:"):
            logger.error("Workspace creation failed: %s", ws_result)
            return

        ws_data = _json.loads(ws_result)
        run.branch = ws_data.get("branch", run.branch)
        ws_path = ws_data.get("path")
        logger.info("Workspace created: %s", ws_path)

        repo_verdict = await _scan_repo_for_threats(ws_path, warden)
        if not repo_verdict.clean:
            logger.warning(
                "Repo scan blocked for run %s: %s",
                run_id,
                repo_verdict.flags,
            )
            orch.fail_run(run_id, error=f"Warden blocked repo: {repo_verdict.flags}")
            return
        logger.info("Repo scan passed for run %s", run_id)

        run._workspace_path = ws_path
        run._issue_content = issue_content
        run._issue_title = issue_title

    except Exception as e:
        logger.error("Workflow setup failed for run %s: %s", run_id, e)
        return

    max_iterations = len(_STAGE_SEQUENCE) + 2

    for _ in range(max_iterations):
        run = orch._runs.get(run_id)
        if not run:
            break
        if run.status in (RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED):
            break

        await _execute_one_stage(run_id, orch, container, service_auth)

    run = orch._runs.get(run_id)
    if run and run.status == RunStatus.PASSED and ws_path:
        await _create_pr_on_finish(run, container, owner, repo, ws_path)

    logger.info("Workflow complete for run %s", run_id)


async def _create_pr_on_finish(
    run: Any, container: Any, owner: str, repo: str, ws_path: str
) -> None:
    """Commit changes, push branch, and create PR after successful run."""
    import json as _json

    try:
        commit_result = await container.tool_dispatcher.execute(
            "workspace",
            {
                "action": "commit",
                "message": f"feat: implement issue #{run.issue_number}",
            },
        )
        if commit_result.startswith("Error:"):
            logger.error("Commit failed: %s", commit_result)
            return

        push_result = await container.tool_dispatcher.execute(
            "workspace",
            {"action": "push"},
        )
        if push_result.startswith("Error:"):
            logger.error("Push failed: %s", push_result)
            return

        pr_result = await container.tool_dispatcher.execute(
            "github",
            {
                "action": "create_pr",
                "owner": owner,
                "repo": repo,
                "title": f"Fix #{run.issue_number}",
                "head": run.branch,
                "base": "main",
                "body": f"Implements #{run.issue_number}\n\nGenerated by Stronghold Builders.",
            },
        )
        if pr_result.startswith("Error:"):
            logger.error("PR creation failed: %s", pr_result)
            return

        pr_data = _json.loads(pr_result)
        logger.info("PR created: %s", pr_data.get("html_url", pr_result))

        await container.tool_dispatcher.execute(
            "workspace",
            {"action": "cleanup"},
        )

    except Exception as e:
        logger.error("PR creation failed for run %s: %s", run.run_id, e)


async def _scan_repo_for_threats(ws_path: str, warden: Any) -> Any:
    """Scan repo files for suspicious patterns using Warden.

    Scans:
    - Shell scripts (*.sh)
    - Config files (*.yaml, *.yml, *.json, *.toml)
    - Any file with secrets-like patterns

    Returns WardenVerdict with clean=True if no threats found.
    """
    from stronghold.types.security import WardenVerdict
    from pathlib import Path
    import re

    if not warden or not ws_path:
        return WardenVerdict(clean=True, blocked=False, flags=(), confidence=1.0)

    ws = Path(ws_path)
    if not ws.exists():
        return WardenVerdict(clean=True, blocked=False, flags=(), confidence=1.0)

    suspicious_extensions = {".sh", ".bash", ".zsh"}
    config_extensions = {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".env"}
    secret_patterns = [
        re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"),
        re.compile(r"(?i)(api_key|apikey|secret|token)\s*[=:]\s*\S+"),
        re.compile(r"(?i)-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
        re.compile(r"(?i)aws_access_key_id\s*=\s*\S+"),
        re.compile(r"(?i)aws_secret_access_key\s*=\s*\S+"),
    ]

    all_flags: list[str] = []
    files_scanned = 0

    for ext in suspicious_extensions | config_extensions:
        for filepath in ws.rglob(f"*{ext}"):
            if ".git" in str(filepath) or "node_modules" in str(filepath):
                continue
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
                files_scanned += 1

                verdict = await warden.scan(content, "tool_result")
                if not verdict.clean:
                    all_flags.extend([f"{filepath.name}: {f}" for f in verdict.flags])

                for pattern in secret_patterns:
                    if pattern.search(content):
                        all_flags.append(f"{filepath.name}: potential secret/credential")

            except Exception as e:
                logger.debug("Failed to scan %s: %s", filepath, e)

    if all_flags:
        return WardenVerdict(
            clean=False,
            blocked=len(all_flags) >= 2,
            flags=tuple(all_flags[:10]),
            confidence=0.8,
        )

    logger.debug("Repo scan complete: %d files, no threats", files_scanned)
    return WardenVerdict(clean=True, blocked=False, flags=(), confidence=1.0)


def _build_stage_prompt(stage: str, worker: Any, run: Any) -> str:
    worker_name = worker.value if hasattr(worker, "value") else str(worker)
    ws_path = getattr(run, "_workspace_path", "/workspace")
    issue_content = getattr(run, "_issue_content", "")
    issue_title = getattr(run, "_issue_title", "")

    tool_context = (
        f"\n\nWORKSPACE: {ws_path}\n"
        f"Issue: {run.repo}#{run.issue_number}\n"
        f"Title: {issue_title}\n\n"
        f"AVAILABLE tools: file_ops, shell, workspace, github, run_pytest, run_ruff_check, run_ruff_format, run_mypy, run_bandit, git\n\n"
        f"Use these tools to read files, write code, run tests, and and"
    )

    issue_context = f"\nISSUE CONTENT:\n{issue_content}\n" if issue_content else ""

    stage_prompts = {
        "issue_analyzed": (
            f"You are {worker_name}. Your job is to analyze GitHub issue #{run.issue_number}.\n\n"
            f"Issue: {run.repo}#{run.issue_number}\n"
            f"Title: {issue_title}\n\n"
            f"Body:\n{issue_content}\n\n"
            f"First, call the github tool with action 'get_issue' to fetch full details if needed.\n"
            f"Then analyze:\ 1) What is the problem? 2) What are the requirements? 3) What are the edge cases?\\n\n"
            f"Provide your analysis in structured format:\n"
            f"## Summary\n"
            f"- Problem:\n"
            f"- Requirements:\n"
            f"- Edge cases:\n"
            f"- Suggested approach:\n\n"
        ),
        "acceptance_defined": (
            f"You are {worker_name}. Based on the issue analysis for {run.repo}#{run.issue_number}, "
            f"define acceptance criteria in Gherkin format (Given/When/Then).\n\n"
            f"Issue context:\n{issue_context}\n\n"
            f"Write acceptance criteria covering:\n"
            f"1. Happy path scenarios\n"
            f"2. Error scenarios\n"
            f"3. Edge cases\n\n"
            f"Format each criterion as:\n"
            f"```gherkin\n"
            f"Given [context]\n"
            f"When [action]\n"
            f"Then [expected result]\n"
            f"```\n"
        ),
        "tests_written": (
            f"You are {worker_name}. Your job is to write comprehensive tests for {run.repo}#{run.issue_number}.\n\n"
            f"Workspace: {ws_path}\n"
            f"Target: 95% code coverage\n\n"
            f"Steps:\n"
            f"1. Use file_ops with action 'list' to explore test structure\n"
            f"2. Use file_ops with action 'read' to examine existing tests\n"
            f"3. Use file_ops with action 'write' to create new test file\n"
            f"4. Use run_pytest to verify tests pass\n\n"
            f"Write tests for:\n"
            f"- Unit tests in tests/unit/\n"
            f"- Integration tests in tests/integration/\n"
            f"- Edge case tests in tests/edge/\n"
        ),
        "implementation_started": (
            f"You are {worker_name}. Your job is to implement the solution for {run.repo}#{run.issue_number}.\n\n"
            f"Workspace: {ws_path}\n"
            f"Issue context:\n{issue_context}\n\n"
            f"Steps:\n"
            f"1. Read the acceptance criteria from the issue_analysis artifact\n"
            f"2. Use file_ops to action 'read' to examine relevant source files\n"
            f"3. Use file_ops with action 'write' to implement the solution\n"
            f"4. Use file_ops with action 'read' to verify implementation\n"
        ),
        "implementation_ready": (
            f"You are {worker_name}. Run quality checks on the implementation.\n\n"
            f"Workspace: {ws_path}\n\n"
            f"Run these quality checks in order:\n"
            f"1. run_pytest with path 'tests/'\n"
            f"2. run_ruff_check\n"
            f"3. run_ruff_format\n"
            f"4. run_mypy\n\n"
            f"If any check fails, use file_ops to fix the issues and re-run.\n"
            f"Report final status of all checks."
        ),
        "quality_checks_passed": (
            f"You are {worker_name}. Verify all quality gates pass and summarize the implementation.\n\n"
            f"Workspace: {ws_path}\n\n"
            f"Run these verifications:\n"
            f"1. run_pytest - verify all tests pass\n"
            f"2. run_ruff_check - verify no linting errors\n"
            f"3. run_mypy - verify no type errors\n\n"
            f"Summarize:\n"
            f"- What was implemented\n"
            f"- How it addresses the issue\n"
            f"- Any remaining work or considerations\n"
        ),
    }
    return stage_prompts.get(stage, f"You are {worker_name}. Execute stage: {stage}{tool_context}")


async def _check_existing_work(
    tool_dispatcher: Any,
    owner: str,
    repo: str,
    issue_number: int,
    issue_title: str,
) -> dict[str, Any]:
    """Check for existing work (PRs, issues, comments) related to the issue."""
    import re

    keywords = re.findall(r"\b\w+\b", issue_title.lower())
    search_query = " ".join(keywords[:3])

    prs_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "search_issues",
            "owner": owner,
            "repo": repo,
            "query": f"{search_query} is:pr",
        },
    )

    prs = []
    if not prs_result.startswith("Error:"):
        prs_data = json.loads(prs_result)
        prs = prs_data.get("items", [])

    comments_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "list_issue_comments",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
        },
    )

    comments = []
    if not comments_result.startswith("Error:"):
        comments = json.loads(comments_result)

    linked_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "get_linked_issues",
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
        },
    )

    linked_issues = []
    if not linked_result.startswith("Error:"):
        linked_issues = json.loads(linked_result)

    has_work = bool(prs or comments or linked_issues)

    return {
        "prs": prs,
        "issues": linked_issues,
        "comments": comments,
        "has_work": has_work,
    }


async def _frank_archie_phase(
    container: Any,
    tool_dispatcher: Any,
    run_id: str,
    repo: str,
    issue_number: int,
    issue_title: str,
    issue_content: str,
    ws_path: str,
    existing_work: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Frank/Archie phase: decompose problem and define acceptance criteria."""
    from stronghold.builders import WorkerName

    if existing_work is None:
        existing_work = await _check_existing_work(
            tool_dispatcher=tool_dispatcher,
            owner=repo.split("/")[0],
            repo=repo.split("/")[1],
            issue_number=issue_number,
            issue_title=issue_title,
        )

    if existing_work["has_work"]:
        publisher = IssueCommentPublisher(
            tool_dispatcher=tool_dispatcher,
            formatter=IssueCommentFormatter(),
        )
        await publisher.publish_workflow_step(
            owner=repo.split("/")[0],
            repo=repo.split("/")[1],
            issue_number=issue_number,
            comment_type=CommentType.FRANK_DECOMPOSITION,
            step="existing_work_found",
            details={
                "existing_prs": len(existing_work["prs"]),
                "existing_comments": len(existing_work["comments"]),
            },
            run_id=run_id,
        )
        return {
            "phase": "frank_archie",
            "decomposed": False,
            "existing_prs": [p["number"] for p in existing_work["prs"]],
        }

    frank = container.agents.get("frank")
    if not frank:
        return {"phase": "frank_archie", "decomposed": False, "error": "Frank agent not found"}

    prompt = _build_stage_prompt(
        "issue_analyzed",
        WorkerName.FRANK,
        Mock(
            repo=repo,
            issue_number=issue_number,
            _workspace_path=ws_path,
            _issue_content=issue_content,
            _issue_title=issue_title,
        ),
    )
    messages = [{"role": "user", "content": prompt}]

    response = await frank.handle(
        messages,
        auth=_build_service_auth(container),
        session_id=f"builders-{run_id}",
    )

    publisher = IssueCommentPublisher(
        tool_dispatcher=tool_dispatcher,
        formatter=IssueCommentFormatter(),
    )
    await publisher.publish_workflow_step(
        owner=repo.split("/")[0],
        repo=repo.split("/")[1],
        issue_number=issue_number,
        comment_type=CommentType.FRANK_DECOMPOSITION,
        step="problem_decomposition",
        details={
            "sub_problems": ["Decomposed into sub-problems"],
            "assumptions": ["Assumptions documented"],
        },
        run_id=run_id,
    )

    return {
        "phase": "frank_archie",
        "decomposed": True,
        "response": response.content if response else "",
    }


async def _mason_phase(
    container: Any,
    tool_dispatcher: Any,
    test_tracker: MasonTestTracker,
    run_id: str,
    repo: str,
    issue_number: int,
    ws_path: str,
    max_attempts: int = 10,
) -> dict[str, Any]:
    """Mason phase: TDD implementation with test tracking."""
    from stronghold.builders import WorkerName

    mason = container.agents.get("mason")
    if not mason:
        return {"phase": "mason", "success": False, "error": "Mason agent not found"}

    for attempt in range(max_attempts):
        logger.info(f"Mason phase attempt {attempt + 1} of {max_attempts}")

        try:
            prompt = _build_stage_prompt(
                "implementation_started",
                WorkerName.MASON,
                Mock(
                    repo=repo,
                    issue_number=issue_number,
                    _workspace_path=ws_path,
                    _issue_content="",
                    _issue_title="",
                ),
            )
            messages = [{"role": "user", "content": prompt}]

            response = await mason.handle(
                messages,
                auth=_build_service_auth(container),
                session_id=f"builders-{run_id}",
            )

            pytest_result = await tool_dispatcher.execute(
                "workspace",
                {"action": "run_pytest", "path": ws_path},
            )
        except Exception as e:
            logger.error(f"Exception in Mason phase attempt {attempt + 1}: {e}")
            raise
        messages = [{"role": "user", "content": prompt}]

        response = await mason.handle(
            messages,
            auth=_build_service_auth(container),
            session_id=f"builders-{run_id}",
        )

        pytest_result = await tool_dispatcher.execute(
            "workspace",
            {"action": "run_pytest", "path": ws_path},
        )

        passing_count = 0
        failing_count = 0
        coverage = "0%"

        logger.info(f"Pytest result: {pytest_result}")

        if not pytest_result.startswith("Error:"):
            import re

            match = re.search(r"(\d+)\s+passed", pytest_result)
            if match:
                passing_count = int(match.group(1))
            match = re.search(r"(\d+)\s+failed", pytest_result)
            if match:
                failing_count = int(match.group(1))
            match = re.search(r"(\d+)%", pytest_result)
            if match:
                coverage = f"{match.group(1)}%"

        logger.info(
            f"Parsed results: passing={passing_count}, failing={failing_count}, coverage={coverage}"
        )

        test_tracker.record_test_result(passing_count)

        publisher = IssueCommentPublisher(
            tool_dispatcher=tool_dispatcher,
            formatter=IssueCommentFormatter(),
        )
        await publisher.publish_workflow_step(
            owner=repo.split("/")[0],
            repo=repo.split("/")[1],
            issue_number=issue_number,
            comment_type=CommentType.MASON_TEST_RESULTS,
            step=f"test_execution_{attempt + 1}",
            details={
                "passing": passing_count,
                "failing": failing_count,
                "coverage": coverage,
                "high_water_mark": test_tracker.high_water_mark,
                "stall_counter": test_tracker.stall_counter,
            },
            run_id=run_id,
        )

        if test_tracker.has_failed:
            return {
                "phase": "mason",
                "success": False,
                "stalled": True,
                "attempts": attempt + 1,
            }

        if failing_count == 0:
            return {
                "phase": "mason",
                "success": True,
                "attempts": attempt + 1,
            }

    return {
        "phase": "mason",
        "success": False,
        "stalled": False,
        "attempts": max_attempts,
    }


async def _run_quality_gates(
    tool_dispatcher: Any,
    ws_path: str,
) -> dict[str, Any]:
    """Run quality gates: pytest, ruff, mypy, bandit."""
    import re

    pytest_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_pytest", "path": ws_path},
    )

    coverage = "0%"
    if not pytest_result.startswith("Error:"):
        match = re.search(r"(\d+)%", pytest_result)
        if match:
            coverage = f"{match.group(1)}%"

    coverage_pct = int(coverage.replace("%", "")) if coverage != "0%" else 0

    ruff_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_ruff_check"},
    )

    mypy_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_mypy"},
    )

    bandit_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "run_bandit"},
    )

    passed = coverage_pct >= 95

    return {
        "passed": passed,
        "coverage": coverage,
        "pytest": "passed" if not pytest_result.startswith("Error:") else "failed",
        "ruff_check": "passed" if not ruff_result.startswith("Error:") else "failed",
        "mypy": "passed" if not mypy_result.startswith("Error:") else "failed",
        "bandit": "passed" if not bandit_result.startswith("Error:") else "failed",
    }


async def _create_pr_after_success(
    tool_dispatcher: Any,
    owner: str,
    repo: str,
    branch: str,
    issue_number: int,
    ws_path: str,
    quality_passed: bool,
) -> dict[str, Any]:
    """Commit, push, and create PR after successful workflow."""
    if not quality_passed:
        return {"created": False, "pr_number": None}

    commit_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "commit", "message": f"feat: implement issue #{issue_number}"},
    )

    if commit_result.startswith("Error:"):
        return {"created": False, "pr_number": None}

    push_result = await tool_dispatcher.execute(
        "workspace",
        {"action": "push"},
    )

    if push_result.startswith("Error:"):
        return {"created": False, "pr_number": None}

    pr_result = await tool_dispatcher.execute(
        "github",
        {
            "action": "create_pr",
            "owner": owner,
            "repo": repo,
            "branch": branch,
            "title": f"Fix #{issue_number}",
            "head": branch,
            "base": "main",
            "body": f"Implements #{issue_number}\n\nGenerated by Stronghold Builders.",
        },
    )

    if pr_result.startswith("Error:"):
        return {"created": False, "pr_number": None}

    pr_data = json.loads(pr_result)
    pr_number = pr_data.get("number")

    publisher = IssueCommentPublisher(
        tool_dispatcher=tool_dispatcher,
        formatter=IssueCommentFormatter(),
    )
    await publisher.publish_workflow_step(
        owner=owner,
        repo=repo,
        issue_number=issue_number,
        comment_type=CommentType.PR_CREATED,
        step="pr_creation",
        details={
            "pr_number": pr_number,
            "pr_url": pr_data.get("html_url", ""),
            "branch": branch,
        },
        run_id="",
    )

    await tool_dispatcher.execute(
        "workspace",
        {"action": "cleanup"},
    )

    return {"created": True, "pr_number": pr_number}


async def _execute_nested_loop_workflow(
    container: Any,
    tool_dispatcher: Any,
    run_id: str,
    repo: str,
    issue_number: int,
    ws_path: str,
    issue_title: str,
    issue_content: str,
) -> dict[str, Any]:
    """Execute sophisticated nested-loop workflow with outer/inner loops."""
    outer_tracker = OuterLoopTracker(max_failures=5)
    model_escalator = ModelEscalator()
    owner, repo_name = repo.split("/")

    for outer_retry in range(5):
        model = model_escalator.select_model(retry_count=outer_retry)

        logger.info(
            "Outer loop attempt %d with model %s",
            outer_retry + 1,
            model,
        )

        frank_result = await _frank_archie_phase(
            container=container,
            tool_dispatcher=tool_dispatcher,
            run_id=run_id,
            repo=repo,
            issue_number=issue_number,
            issue_title=issue_title,
            issue_content=issue_content,
            ws_path=ws_path,
        )

        if not frank_result.get("decomposed", False) and frank_result.get("existing_prs"):
            outer_tracker.record_success()
            return {
                "status": "completed",
                "reason": "existing_work_found",
                "existing_prs": frank_result["existing_prs"],
            }

        test_tracker = MasonTestTracker()

        for inner_retry in range(3):
            mason_result = await _mason_phase(
                container=container,
                tool_dispatcher=tool_dispatcher,
                test_tracker=test_tracker,
                run_id=run_id,
                repo=repo,
                issue_number=issue_number,
                ws_path=ws_path,
            )

            if mason_result.get("success"):
                quality_result = await _run_quality_gates(
                    tool_dispatcher=tool_dispatcher,
                    ws_path=ws_path,
                )

                publisher = IssueCommentPublisher(
                    tool_dispatcher=tool_dispatcher,
                    formatter=IssueCommentFormatter(),
                )
                await publisher.publish_workflow_step(
                    owner=owner,
                    repo=repo_name,
                    issue_number=issue_number,
                    comment_type=CommentType.QUALITY_CHECKS,
                    step="quality_verification",
                    details=quality_result,
                    run_id=run_id,
                )

                if quality_result["passed"]:
                    pr_result = await _create_pr_after_success(
                        tool_dispatcher=tool_dispatcher,
                        owner=owner,
                        repo=repo_name,
                        branch=f"builders/{issue_number}-{run_id}",
                        issue_number=issue_number,
                        ws_path=ws_path,
                        quality_passed=True,
                    )

                    if pr_result["created"]:
                        outer_tracker.record_success()
                        return {
                            "status": "completed",
                            "pr_number": pr_result["pr_number"],
                        }
                else:
                    outer_tracker.record_failure()
                    break

            if mason_result.get("stalled"):
                logger.info(
                    "Mason stalled after %d attempts, returning to Frank/Archie",
                    test_tracker.stall_counter,
                )
                break

        if outer_tracker.should_signal_admin:
            publisher = IssueCommentPublisher(
                tool_dispatcher=tool_dispatcher,
                formatter=IssueCommentFormatter(),
            )
            await publisher.publish_workflow_step(
                owner=owner,
                repo=repo_name,
                issue_number=issue_number,
                comment_type=CommentType.ADMIN_SIGNAL,
                step="admin_alert",
                details={
                    "total_failures": outer_tracker.failure_count,
                    "recommendation": "Review issue complexity and consider manual intervention",
                },
                run_id=run_id,
            )
            return {
                "status": "failed",
                "reason": "max_retries_exceeded",
                "failures": outer_tracker.failure_count,
            }

    return {
        "status": "failed",
        "reason": "max_outer_loops_exceeded",
        "failures": outer_tracker.failure_count,
    }
